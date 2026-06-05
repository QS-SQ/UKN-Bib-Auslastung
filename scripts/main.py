"""
Main File for the UKN-Bib-Auslastung project used in the action workflow
"""

import os
from dotenv import load_dotenv
from methods import read_email, preprocess_data, map_router_to_location, calc_occupancy, visualize_occupancy    

load_dotenv()
flags = ['not read', 'not processed', 'not mapped', 'not calculated']

df_data, timestamp, flags[0] = read_email()

if flags[0] == 'ok':
    df_data, flags[1] = preprocess_data(df_data)

if flags[1] == 'ok':
    df_data, flags[2] = map_router_to_location(df_data)
    
if flags[2] != 'No mapping found in environment':
    occ, flags[3] = calc_occupancy(df_data)
    
if flags[3] == 'ok':
    path = os.path.join(os.getcwd(), 'docs/temp_storage/current_capacity_utilization.jpg')
    visualize_occupancy(occ, path, timestamp)

# send error message if any of the flags is not 'ok'
if any(flag != 'ok' for flag in flags):
    error_message = 'Error in processing: ' + '; '.join([flag for flag in flags if flag != 'ok'])
    print(error_message)