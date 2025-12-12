export interface AwsConfig {
  region: string;
  accountId: string;
  ecrRepository: string;
  instanceType: string;
  volumeSize: number;
}

export interface RunningInstance {
  id: string;
  name: string;
  status: 'running' | 'pending' | 'stopping' | 'stopped';
  publicDns: string;
  instanceType: string;
  launchTime: string;
}

export interface LogEntry {
  timestamp: string;
  message: string;
  type: 'info' | 'error' | 'warning' | 'success';
}

export interface TransferStatus {
  progress: number;
  isUploading: boolean;
  isDownloading: boolean;
  currentFile: string;
}

export interface AwsMetadata {
  repositories: string[];
  securityGroups: string[];
}

export interface DeployResponse {
  status: string;
  instance: {
    id: string;
    publicDns: string;
    instanceType: string;
  };
  logs: string[];
}

export interface ApiMessage {
  status: string;
  message?: string;
}

export interface DeployStreamEvent {
  event: "log" | "progress" | "complete" | "error";
  data: unknown;
}

export interface AssumeRoleLoginRequest {
  roleArn: string;
  externalId?: string;
  region: string;
  sessionName?: string;
}

export interface AssumeRoleLoginResponse {
  status: string;
  session_id: string;
  expires_at: string;
  account_id: string;
  message: string;
}

export const AWS_REGIONS = [
  { value: 'us-east-1', label: 'US East (N. Virginia)' },
  { value: 'us-east-2', label: 'US East (Ohio)' },
  { value: 'us-west-1', label: 'US West (N. California)' },
  { value: 'us-west-2', label: 'US West (Oregon)' },
] as const;

export const INSTANCE_TYPES = [
  { value: 't3.micro', label: 't3.micro (CPU)', category: 'CPU' },
  { value: 't3.small', label: 't3.small (CPU)', category: 'CPU' },
  { value: 't3.medium', label: 't3.medium (CPU)', category: 'CPU' },
  { value: 't3.large', label: 't3.large (CPU)', category: 'CPU' },
  { value: 'hpc7a.96xlarge', label: 'hpc7a.96xlarge (HPC)', category: 'HPC' },
  { value: 'p3.2xlarge', label: 'p3.2xlarge (GPU)', category: 'GPU' },
  { value: 'p3.8xlarge', label: 'p3.8xlarge (GPU)', category: 'GPU' },
  { value: 'g4dn.xlarge', label: 'g4dn.xlarge (GPU)', category: 'GPU' },
] as const;
