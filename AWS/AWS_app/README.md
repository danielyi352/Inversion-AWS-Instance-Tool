# Inversion Deployer

A web-based application for deploying Docker containers to AWS EC2 instances with a modern, user-friendly interface. This tool simplifies the process of launching EC2 instances, managing ECR repositories, and running containerized workloads on AWS.

## Features

- 🔐 **Secure Authentication**: Login with IAM Role ARN using AWS STS assume role
- 🐳 **Docker Image Management**: Upload Docker images to ECR directly from the UI
- 🚀 **EC2 Instance Deployment**: Launch EC2 instances with customizable configurations
- 📦 **Container Management**: Browse files, view logs, and manage containers on running instances
- 🔧 **SSM-Based Access**: Secure instance access via AWS Systems Manager (no SSH keys required)
- 📊 **Real-time Logs**: Stream deployment logs and container output in real-time
- 🎯 **Auto-Detection**: Automatically selects appropriate AMI based on repository name

## Architecture

- **Backend**: FastAPI (Python) - REST API server running on port 8000
- **Frontend**: React + TypeScript + Vite - Web UI running on port 8080
- **AWS Services**: EC2, ECR, SSM, S3, IAM

## Prerequisites

- **Python 3.11+** (for backend)
- **Node.js 18+** and **npm** (for frontend)
- **Docker** (installed and running on the backend server for image uploads)
- **AWS Account** with appropriate IAM permissions
- **IAM Role** with permissions to:
  - Assume roles (for login)
  - Create/manage EC2 instances
  - Access ECR repositories
  - Use SSM for instance management
  - Access S3 for file transfers

## Setup Instructions

### 1. Clone the Repository

```bash
git clone <repository-url>
cd inversion-deployer-dev/AWS/AWS_app
```

### 2. Backend Setup (Python/FastAPI)

#### Option A: Using Conda (Recommended)

```bash
# Create conda environment from environment.yml
conda env create -f environment.yml

# Activate the environment
conda activate aws-deployer

# Note: All dependencies are included in environment.yml
```

#### Option B: Using pip/virtualenv

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies from requirements.txt
pip install -r requirements.txt
```

### 3. Frontend Setup (React/Vite)

```bash
# Navigate to frontend directory
cd aws-deployer-hub-main

# Install dependencies
npm install

# The frontend is ready to run
```

### 4. Environment Configuration

Create a `.env` file in the `aws_deployer_app` directory for AWS credentials:

```bash
cd aws_deployer_app
touch .env
# On Windows:
# type nul > .env
```

Add your AWS credentials to `.env`:

```env
AWS_ACCESS_KEY_ID=your_access_key_here
AWS_SECRET_ACCESS_KEY=your_secret_key_here
```

**Note**: These credentials are used to assume the IAM role you provide during login. The role you assume should have full permissions for EC2, ECR, SSM, and S3 operations.

**Alternative**: You can also use AWS Secrets Manager or Parameter Store (see backend code for implementation details).

### 5. Running the Application

#### Start the Backend Server

```bash
# From the aws_deployer_app directory
cd aws_deployer_app

# Activate your environment first (conda or venv)
conda activate aws-deployer  # or: source venv/bin/activate

# Run the FastAPI server
uvicorn api_server:app --reload --host 127.0.0.1 --port 8000
```

The backend API will be available at `http://127.0.0.1:8000`

#### Start the Frontend Development Server

```bash
# From the aws-deployer-hub-main directory
cd aws-deployer-hub-main

# Start the Vite dev server
npm run dev
```

The frontend will be available at `http://localhost:8080`

### 6. Access the Application

1. Open your browser and navigate to `http://localhost:8080`
2. You'll be prompted to login with an IAM Role ARN
3. Enter your IAM Role ARN (e.g., `arn:aws:iam::123456789012:role/YourRoleName`)
4. Optionally provide an External ID if your role requires it
5. Select your AWS region
6. Click "Login"

## Usage Guide

### 1. Connect to a Repository

1. After logging in, select an ECR repository from the dropdown
2. Click "Connect" to check the repository status
3. If the repository is empty, you'll see a message indicating so

### 2. Upload Docker Image

1. If the repository is empty, the "Push Docker Image to ECR" section will appear
2. Ensure Docker is running on your backend server
3. Build your Docker image locally: `docker build -t myimage:latest .`
4. Export to tar file: `docker save myimage:latest -o myimage.tar`
5. Select the tar file and enter an image tag (default: `latest`)
6. Click "Push to ECR"

### 3. Configure Instance Settings

1. Once your repository has images, the "Instance Configuration" section appears
2. Configure:
   - **Instance Type**: Choose from CPU, GPU, or HPC instances
   - **OS Image (AMI)**: Auto-detect, Amazon Linux 2023, Deep Learning GPU AMI, Ubuntu 22.04, or Custom AMI ID
   - **Volume Size**: EBS volume size in GiB (1-2048)
   - **Volume Type**: gp3 (recommended), gp2, io1, io2, st1, or sc1
   - **Availability Zone**: Optional (uses default if empty)
   - **Subnet ID**: Optional (uses default VPC if empty)
   - **User Data**: Optional bash script to run on instance startup

### 4. Deploy Instance

1. Review your instance configuration
2. Click "Deploy" button
3. Monitor the progress in the "Progress and Logs" section at the bottom
4. Once deployment completes, your instance will appear in the "Status & Instances" section

### 5. Manage Containers

1. Select an instance from the "Running Instances" dropdown
2. **Browse Files**: Navigate the container filesystem and download files
3. **View Logs**: See real-time container logs with auto-refresh
4. **Terminate**: Stop and terminate the selected instance

## Project Structure

```
AWS_app/
├── aws_deployer_app/          # Backend (Python/FastAPI)
│   ├── api_server.py          # Main FastAPI application
│   ├── docker_routes.py       # Docker/ECR related endpoints
│   ├── file_transfer_routes.py # File transfer and container management
│   ├── main.py                # Legacy PySide6 GUI (optional)
│   └── .env                   # AWS credentials (create this)
│
├── aws-deployer-hub-main/      # Frontend (React/TypeScript)
│   ├── src/
│   │   ├── components/        # React components
│   │   ├── hooks/             # Custom React hooks
│   │   ├── lib/               # API client and utilities
│   │   └── types/             # TypeScript type definitions
│   └── package.json
│
├── environment.yml             # Conda environment definition
├── requirements.txt           # Python dependencies for pip users
└── README.md                  # This file
```

## API Endpoints

### Authentication

- `POST /api/auth/assume-role` - Login with IAM Role ARN

### Metadata

- `GET /api/metadata` - Get ECR repositories and security groups
- `GET /api/repositories/{repository}/status` - Check repository status

### Deployment

- `POST /api/deploy` - Deploy instance (synchronous)
- `GET /api/deploy/stream` - Deploy instance (streaming logs)

### Docker/ECR

- `GET /api/docker/check` - Check Docker availability
- `POST /api/ecr/push-image` - Upload Docker image to ECR
- `DELETE /api/ecr/repositories/{repository}` - Clear repository

### Instance Management

- `GET /api/instances` - List running instances
- `POST /api/terminate` - Terminate instance

### File Transfer

- `POST /api/upload` - Upload file to instance/container
- `GET /api/download` - Download file from instance/container
- `GET /api/list-files` - List files in container/instance
- `GET /api/container-logs` - Get container logs
- `GET /api/container-logs/download` - Download container logs

## Troubleshooting

### Backend Issues

**Issue**: `ModuleNotFoundError: No module named 'fastapi'`

- **Solution**: Ensure your Python environment is activated and dependencies are installed

**Issue**: `Docker is not running`

- **Solution**: Start Docker Desktop or Docker daemon on your system

**Issue**: `Invalid or expired session`

- **Solution**: Re-login with your IAM Role ARN (sessions expire after 1 hour)

### Frontend Issues

**Issue**: `Failed to fetch` errors

- **Solution**: Ensure the backend server is running on port 8000

**Issue**: CORS errors

- **Solution**: The backend has CORS enabled for all origins. If issues persist, check the backend is running and accessible

### AWS Issues

**Issue**: `Repository not found`

- **Solution**: Ensure you're connected to the correct AWS region and the repository exists

**Issue**: `SSM connection failed`

- **Solution**: Ensure the EC2 instance has an IAM role with `AmazonSSMManagedInstanceCore` policy attached

**Issue**: `Failed to launch instance`

- **Solution**: Check your IAM permissions, region availability, and instance type availability in the selected region

## Development

### Backend Development

```bash
# Run with auto-reload for development
uvicorn api_server:app --reload --host 127.0.0.1 --port 8000
```

### Frontend Development

```bash
# Run Vite dev server with hot reload
npm run dev
```

### Building for Production

**Frontend**:

```bash
cd aws-deployer-hub-main
npm run build
```

**Backend**: The FastAPI server can be deployed using any ASGI server (uvicorn, gunicorn, etc.)

## Security Notes

- AWS credentials in `.env` are used only to assume the IAM role you provide
- All instance access is via SSM (no SSH keys required)
- Security groups are created automatically with no SSH rules (SSM uses HTTPS port 443)
- Session tokens expire after 1 hour for security
- Consider using AWS Secrets Manager or Parameter Store for production deployments
