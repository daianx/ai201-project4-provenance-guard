import csv
import subprocess
import random
import time
import os
import json

def process_batch(filename, sample_size=50, delay=6.0):
    """
    Reads user_id and Content from humanvsAI.csv, constructs
    the JSON payload, and executes the curl command.
    The delay is set to 6 seconds to adhere to the 10 requests/minute rate limit.
    """
    requests_to_send = []
    
    if not os.path.exists(filename):
        print(f"Error: {filename} not found.")
        return

    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Construct the payload dictionary
                payload = {
                    "text": row['Content'],
                    "creator_id": row['user_id']
                }
                requests_to_send.append(json.dumps(payload))
                
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    if not requests_to_send:
        print("No data found in CSV.")
        return

    actual_sample_size = min(len(requests_to_send), sample_size)
    sample = random.sample(requests_to_send, actual_sample_size)
    print(f"Selected {actual_sample_size} random samples from {len(requests_to_send)} total.")
    print(f"Rate limiting active: {60/delay} requests per minute.")

    for i, payload in enumerate(sample):
        print(f"[{i+1}/{actual_sample_size}] Executing request...")
        
        # Build the command using a list of arguments.
        # This is the safest way to execute curl via Python.
        cmd_args = [
            "curl", "-s", "-X", "POST", "http://localhost:5000/submit",
            "-H", "Content-Type: application/json",
            "-d", payload
        ]
        
        try:
            # shell=False is safe and handles the payload correctly
            subprocess.run(cmd_args, shell=False)
        except Exception as e:
            print(f"Failed to execute command: {e}")
            
        time.sleep(delay)
        print("-" * 40)

if __name__ == "__main__":
    process_batch('humanvsAI.csv', sample_size=50, delay=6.0)