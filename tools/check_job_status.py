#!/usr/bin/env python3
from google.cloud import aiplatform
aiplatform.init(project='gen-lang-client-0699310395', location='us-central1')
jobs = aiplatform.CustomJob.list(order_by='create_time desc')
for j in jobs[:5]:
    print(f"Job Name: {j.display_name}")
    print(f"State: {j.state}")
    if j.error:
        print(f"Error Code: {j.error.code}")
        print(f"Error Message: {j.error.message}")
    print("-" * 50)
