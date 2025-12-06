#!/bin/bash
echo "Initializing LocalStack S3..."
awslocal s3 mb s3://my-bucket
echo "S3 bucket 'my-bucket' created."
