import os

port = os.getenv('PORT')
print(f"PORT: {port}")
print(type(port))
port = os.environ.get('PORT')
print(f"PORT: {port}")
print(type(port))
