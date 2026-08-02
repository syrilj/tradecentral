#!/usr/bin/env python3
from google.cloud import aiplatform

aiplatform.init(project='gen-lang-client-0699310395', location='us-central1')
job = aiplatform.CustomJob.get('projects/14083780676/locations/us-central1/customJobs/2749708440233312256')
print("Job Name:", job.display_name)
print("State:", job.state)
print("Error:", job.error)
