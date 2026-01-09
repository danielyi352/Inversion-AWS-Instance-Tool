#!/bin/bash
# Script to attach SSM Session Manager policy to IAM users
# Usage: ./attach_ssm_policy.sh USERNAME1 USERNAME2 ...

POLICY_NAME="SSMSessionManagerAccess"
POLICY_FILE="user_ssm_policy.json"

if [ ! -f "$POLICY_FILE" ]; then
    echo "Error: $POLICY_FILE not found"
    exit 1
fi

for USERNAME in "$@"; do
    echo "Attaching policy to user: $USERNAME"
    aws iam put-user-policy \
        --user-name "$USERNAME" \
        --policy-name "$POLICY_NAME" \
        --policy-document "file://$POLICY_FILE"
    
    if [ $? -eq 0 ]; then
        echo "✓ Policy attached to $USERNAME"
    else
        echo "✗ Failed to attach policy to $USERNAME"
    fi
done

echo "Done!"
