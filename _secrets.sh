#!/bin/bash

# Function to create or update a secret
create_or_update_secret() {
  local secret_name="$1"
  local secret_file="$2"

  # Check if the secret exists
  aws secretsmanager describe-secret --secret-id "$secret_name" > /dev/null 2>&1

  if [ $? -eq 0 ]; then
    # Secret exists, update it
    echo "Updating secret: $secret_name"
    aws secretsmanager update-secret --secret-id "$secret_name" --secret-string file://"$secret_file"
  else
    # Secret does not exist, create it
    echo "Creating secret: $secret_name"
    aws secretsmanager create-secret --name "$secret_name" --secret-string file://"$secret_file"
  fi

  echo "Secret '$secret_name' is now up-to-date."
}

# Call the function for each secret
create_or_update_secret "prod/calpilot/gcp" ".creds.gcp.json"
create_or_update_secret "prod/calpilot/gemini" ".creds.gemini.json"
