#!/usr/bin/env bash
# Setup & Authenticate GCP with Credit Protection

echo "======================================================================"
echo "  GCP VERTEX AI CREDIT AUTHENTICATION & SAFETY SETUP"
echo "======================================================================"

# Step 1: Login to Google Cloud
echo -e "\n1. Authenticating gcloud CLI..."
gcloud auth login

# Step 2: Application Default Credentials (ADC) for Python SDK
echo -e "\n2. Authenticating Application Default Credentials (ADC)..."
gcloud auth application-default login

# Step 3: Set GCP Project ID
DEFAULT_PROJECT="gen-lang-client-0699310395"
read -p "Enter your GCP Project ID [default: ${DEFAULT_PROJECT}]: " GCP_PROJECT_ID
GCP_PROJECT_ID=${GCP_PROJECT_ID:-$DEFAULT_PROJECT}
gcloud config set project "$GCP_PROJECT_ID"
export GCP_PROJECT="$GCP_PROJECT_ID"

# Step 4: Verify Billing Account & Credits
echo -e "\n======================================================================"
echo "  STEPS TO CONFIRM YOUR $1,500 CREDIT IS ACTIVE IN GCP CONSOLE:"
echo "======================================================================"
echo "  1. Go to GCP Console: https://console.cloud.google.com/billing"
echo "  2. Click 'Billing Account Overview'."
echo "  3. Look for 'Credits' card -> Confirm '$1,500 Gen AI Credit' is ACTIVE."
echo "  4. Click 'Budgets & Alerts' -> Create Budget Alert at $5.00 / $50.00."
echo "======================================================================"

echo -e "\n[SUCCESS] Setup complete! Your environment is ready for Vertex AI."
