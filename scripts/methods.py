"""
Method File for the UKN-Bib-Auslastung project used in the action workflow
"""

# import necessary libraries
import pandas as pd
import matplotlib.pyplot as plt
import imaplib
import email
from io import BytesIO, StringIO
import os

def extract_csv_attachment(mail, id):
    """
    Extracts the CSV attachment from an email message.

    Args:
        mail (IMAP4): An instance of the IMAP4 class representing the email connection.
        id (bytes): The ID of the email message to extract the attachment from.
    Returns:
        df_data (DataFrame): DataFrame containing the data from the CSV attachment.
        timestamp (str): Timestamp of the email.
        flag (str): Status flag indicating success or failure of the attachment extraction process.
    """
    flag='ok'
    _, msg_data = mail.fetch(id, "(RFC822)")
    raw_msg = msg_data[0][1]
    msg = email.message_from_bytes(raw_msg)
        
    # extract timestamp from email header and csv attachment
    timestamp = pd.to_datetime(msg['Date']).tz_localize(None).replace(second=0) 
    df_data = None
    
    for part in msg.walk():
        filename = part.get_filename()
        if filename and filename.lower().endswith('.csv'):
            payload = part.get_payload(decode=True)
            df_data = pd.read_csv(BytesIO(payload), delimiter=',', skiprows=8, on_bad_lines='skip')
            
    if df_data is None:
        flag = 'no csv attachment in email found'
              
    return df_data, timestamp, flag


def read_email():
    """
    Reads the most recent email (last 24h) with a specific subject filter and extracts the CSV attachment 
    as a DataFrame.

    Returns:
        df_data (DataFrame): DataFrame containing the data from the CSV attachment.
        timestamp (str): Timestamp of the email.
        flag (str): Status flag indicating success or failure of the email reading process.
    """
    # Connect to the email server and log in
    try:
        server = os.getenv("SERVER")
        port = int(os.getenv("PORT"))
        port = 993
        if port == 993:
            mail = imaplib.IMAP4_SSL(server, port)
        else:
            mail = imaplib.IMAP4(server, port)
            mail.starttls()
        mail.login(os.getenv("USER"), os.getenv("PASSWORD"))
        mail.select("INBOX")
    except Exception as e:
        flag = f'Error connecting to email server, {e}'
        return None, None, flag

    # Search for emails from a specific sender that were sent in the last 24 hours
    since_date = (pd.Timestamp.now() - pd.Timedelta(days=1)).strftime('%d-%b-%Y')
    _, data = mail.search(None, '(ALL FROM "{}" SINCE {})'.format(os.getenv("SENDER"), since_date))
    mail_ids = data[0].split()

    # find most recent email and extract csv attachment
    if mail_ids: 
        return extract_csv_attachment(mail, mail_ids[-1])
    
    else:
        flag = 'no email found'
        return None, None, flag
 
    
def preprocess_data(df_data):
    """ 
    Preprocesses the extracted DataFrame by removing unnecessary columns 
    and summing up the Average Number of Users and Peak Number of Users for each AP Name.
    
    Args:
        df_data (DataFrame): DataFrame containing the data from the CSV attachment.
    Returns:
        df_data (DataFrame): Preprocessed DataFrame with unnecessary columns removed and summed up user numbers.
        flag (str): Status flag indicating success or failure of the preprocessing process.
    """
    flag = 'ok'
    
    # remove column Radio Type if it exists
    if 'Radio Type' in df_data.columns:
        df_data = df_data.drop(columns=['Radio Type'])
    else:
        flag = 'column Radio Type not found'
        
    # remove column AP MACAddress if it exists
    if 'AP MACAddress' in df_data.columns:
        df_data = df_data.drop(columns=['AP MACAddress'])
    else:
        flag = flag + ' and column AP MACAddress not found' if flag != 'ok' else 'column AP MACAddress not found'
        
    # add columns Average Number of Users and Peak Number of Users if they have the same AP Name
    if 'AP Name' in df_data.columns and 'Average Number of Users' in df_data.columns and 'Peak Number of Users' in df_data.columns:
        df_data['Average Number of Users'] = df_data.groupby('AP Name')['Average Number of Users'].transform('sum')
        df_data['Peak Number of Users'] = df_data.groupby('AP Name')['Peak Number of Users'].transform('sum')
        df_data = df_data.drop_duplicates(subset=['AP Name'])
        df_data = df_data.reset_index(drop=True)
    else:
        flag = flag + ' and necessary columns for summing up not found' if flag != 'ok' else 'necessary columns for summing up not found'
        
    return df_data, flag


def map_router_to_location(df_data):
    """ 
    Maps the router names in the DataFrame to their corresponding locations using a CSV file 
    containing the mapping information.
    
    Args:
        df_data (DataFrame): DataFrame containing the data from the CSV attachment.
    Returns:
        df_data (DataFrame): DataFrame with an additional column for the mapped locations.
        flag (str): Status flag indicating success or failure of the mapping process.
    """
    flag = 'ok'
    
    mapping_str = os.getenv("MAPPING")
    if mapping_str:
        router_map = pd.read_csv(StringIO(mapping_str), sep=';')
    else:
        flag = 'No mapping found in environment'
        return df_data, flag
    
    # map router names to locations using the csv file
    router_area_map = dict(zip(router_map.iloc[:, 1].astype(str).str.strip(), router_map.iloc[:, 2].astype(str).str.strip()))
    
    # add new column to df_data with ROUTER_AREA_MAP from config.py
    df_data['AP Name'] = df_data['AP Name'].astype(str).str.strip()
    df_data['Location'] = df_data['AP Name'].map(router_area_map)

    # check if there are any AP Names that could not be mapped to a location and print them out
    unmapped_aps = df_data[df_data['Location'].isna()]['AP Name'].unique()
    if len(unmapped_aps) > 0:
        flag = 'the following AP Names could not be mapped to a location: ' + ', '.join(unmapped_aps)
            
    # check if there are any AP Names in ROUTER_AREA_MAP that are not in the df_data and print them out
    missing_aps = set(router_area_map.keys()) - set(df_data['AP Name'])
    if len(missing_aps) > 0:
        flag = flag + ' and the following AP Names from the mapping file are not in the data: ' + ', '.join(missing_aps) if flag != 'ok' else 'the following AP Names from the mapping file are not in the data: ' + ', '.join(missing_aps)
            
    return df_data, flag


def calc_occupancy(df_data):
    """
    Calculate the occupancy for each location based on the Average Number of Users 
    and the capacity defined in the capacity map.

    Args:
        df_data (DataFrame): DataFrame containing the data from the CSV attachment with mapped locations.
        capacity_map (dict): Dictionary mapping locations to their capacities.
    Returns:
        occup (dict): Dictionary containing the occupancy for each location.
    """
    flag = 'ok'
    
    # load capacity map from environment variable and create a dictionary
    capacity_str = os.getenv("CAPACITY")
    if capacity_str:
        capacity_map = pd.read_csv(StringIO(capacity_str), sep=';')
    else:
        flag = 'No capacity data found in environment'
        return {}, flag
    capacity_map = dict(zip(capacity_map.iloc[:, 0].astype(str).str.strip(), capacity_map.iloc[:, 1].astype(float)))
    
    occup = {}
    
    for loc in capacity_map.keys():
        if loc in df_data['Location'].values:
            avg_users = df_data[df_data['Location'] == loc]['Average Number of Users'].sum()
            capacity = capacity_map[loc]
            if capacity > 0:
                occupancy = min(avg_users * capacity, 1) * 100
            else:
                occupancy = 0
            occup[loc] = occupancy
        else:
            flag = flag + f' and location {loc} not found in data' if flag != 'ok' else f'location {loc} not found in data'
            occup[loc] = 0
            
    # filter occupancy dictionary
    occup = {k: v for k, v in occup.items() if k not in ['nf', 'na']}
            
    return occup, flag


def visualize_occupancy(occupancy, path, time, show=False):
    """ 
    Plot occupancy as a bar chart and save it to the specified path. 
    
    Args:
        occupancy (dict): Dictionary containing the occupancy for each location.
        path (str): Path to save the generated plot.
        time (str): Timestamp to include in the plot title.
        show (bool): Flag indicating whether to display the plot after saving it.
    """
    
    # colored bars based on occupancy levels
    colors = []
    for value in occupancy.values():
        if value > 80:
            colors.append("#EF4444")
        elif value > 60:
            colors.append("#FB923C")
        elif value > 40:
            colors.append("#FACC15")
        else:
            colors.append("#19A54D")
    
    plt.figure(figsize=(10, 6))
    # background reference bars at 100% for each category
    keys = list(occupancy.keys())
    values = list(occupancy.values())
    plt.barh(keys, [100] * len(keys), color="#E5E7EB", alpha=0.3, height=0.62, edgecolor='k', zorder=0)
    # draw actual values on top of the reference bars
    plt.barh(keys, values, color=colors, alpha=0.7, height=0.62, zorder=2)
    plt.xlim(0, 100)
    plt.xticks([])
    plt.yticks(keys, fontsize=12)
    plt.tick_params(axis='y', length=0)
    ax = plt.gca()
    ax.text(1, 0, time, transform=ax.transAxes, ha='right', va='bottom', fontsize=8, color='#6B7280')
    for spine in ax.spines.values():
        spine.set_visible(False)
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    if show:
        plt.show()
    
    plt.close('all')