import type { AwsConfig, AwsMetadata, DeployResponse, RunningInstance, AssumeRoleLoginRequest, AssumeRoleLoginResponse } from "@/types/aws";

// Use production backend first, fallback to local for development
const API_BASE = import.meta.env.MODE === 'production'
  ? "https://inversion-aws-instance-tool.onrender.com/api"
  : (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api");

// Get session ID from localStorage
function getSessionId(): string | null {
  return localStorage.getItem('aws_session_id');
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const sessionId = getSessionId();
  const headers: HeadersInit = { "Content-Type": "application/json" };
  
  // Add session ID to headers if available
  if (sessionId) {
    headers["X-Session-ID"] = sessionId;
  }
  
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers,
      ...options,
    });
    
    if (!res.ok) {
      const detail = await res.text();
      
      // Check for session expiration (401 status or session-related errors)
      if (res.status === 401 || detail.includes('Invalid or expired session') || detail.includes('Session expired')) {
        // Clear expired session
        localStorage.removeItem('aws_session_id');
        // Throw a specific error that can be caught by components
        const sessionError = new Error('SESSION_EXPIRED');
        (sessionError as any).isSessionExpired = true;
        (sessionError as any).originalMessage = detail;
        throw sessionError;
      }
      
      throw new Error(detail || res.statusText);
    }
    return res.json();
  } catch (error) {
    // Re-throw session expiration errors as-is
    if (error instanceof Error && (error as any).isSessionExpired) {
      throw error;
    }
    
    // Provide more helpful error messages
    if (error instanceof TypeError && error.message === 'Failed to fetch') {
      throw new Error(
        `Cannot connect to backend server at ${API_BASE}. ` +
        `Make sure the backend is running on port 8000. ` +
        `Error: ${error.message}`
      );
    }
    throw error;
  }
}

export function loginSso(profile: string, region: string) {
  return apiFetch<{ status: string; message: string }>("/sso/login", {
    method: "POST",
    body: JSON.stringify({ profile, region }),
  });
}

export function cloudformationLogin(accountId: string, region: string) {
  return apiFetch<{
    status: string;
    account_id: string;
    region: string;
    stack_name: string;
    cloudformation_console_url: string;
    template_s3_url: string;
    role_arn_format: string;
    instructions: string;
  }>("/auth/cloudformation/login", {
    method: "POST",
    body: JSON.stringify({
      account_id: accountId,
      region: region,
    }),
  });
}

export function cloudformationVerify(accountId: string, region: string) {
  return apiFetch<{
    status: string;
    session_id: string;
    expires_at: string;
    account_id: string;
    role_arn: string;
    message: string;
    attempt: number;
  }>("/auth/cloudformation/verify", {
    method: "POST",
    body: JSON.stringify({
      account_id: accountId,
      region: region,
    }),
  });
}

export function assumeRoleLogin(request: AssumeRoleLoginRequest) {
  return apiFetch<AssumeRoleLoginResponse>("/auth/assume-role", {
    method: "POST",
    body: JSON.stringify({
      role_arn: request.roleArn,
      account_id: request.accountId,
      external_id: request.externalId,
      region: request.region,
    }),
  });
}

export function fetchMetadata(region: string = "us-east-1") {
  // Session ID is automatically included via apiFetch
  return apiFetch<AwsMetadata>(`/metadata?region=${encodeURIComponent(region)}`);
}

export function fetchInstances(region: string = "us-east-1") {
  // Session ID is automatically included via apiFetch
  return apiFetch<{ instances: RunningInstance[] }>(
    `/instances?region=${encodeURIComponent(region)}`
  );
}

export function checkRepositoryStatus(repository: string, region: string = "us-east-1") {
  // Session ID is automatically included via apiFetch
  return apiFetch<{
    exists: boolean;
    hasImages: boolean;
    imageCount: number;
    images: Array<{imageTag: string; imageDigest: string}>;
    repositoryUri?: string;
    message: string;
  }>(`/repositories/${encodeURIComponent(repository)}/status?region=${encodeURIComponent(region)}`);
}

export function checkDockerAvailability() {
  return apiFetch<{
    available: boolean;
    version: string | null;
    daemon_running: boolean;
    message: string;
  }>("/docker/check");
}

export function pushImageToEcr(
  repository: string,
  tarFile: File,
  imageTag: string = "latest",
  region: string = "us-east-1"
) {
  const sessionId = getSessionId();
  const formData = new FormData();
  formData.append('repository', repository);
  formData.append('image_tag', imageTag);
  formData.append('region', region);
  formData.append('tar_file', tarFile);

  const headers: HeadersInit = {};
  if (sessionId) {
    headers['X-Session-ID'] = sessionId;
  }

  return fetch(`${API_BASE}/ecr/push-image`, {
    method: 'POST',
    headers,
    body: formData,
  }).then(async (res) => {
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(detail || res.statusText);
    }
    return res.json();
  });
}

export function clearRepository(
  repository: string,
  region: string = "us-east-1"
) {
  return apiFetch<{
    status: string;
    message: string;
    deletedCount: number;
  }>(`/ecr/repositories/${repository}?region=${region}`, {
    method: "DELETE",
  });
}

export function deploy(config: AwsConfig & { accountId: string }) {
  // Session ID is automatically included via apiFetch
  return apiFetch<DeployResponse>("/deploy", {
    method: "POST",
    body: JSON.stringify({
      region: config.region,
      account_id: config.accountId,
      repository: config.ecrRepository,
      instance_type: config.instanceType,
      security_group: null,  // Will use default automatically
      volume_size: config.volumeSize,
      volume_type: config.volumeType || 'gp3',
      availability_zone: config.availabilityZone || null,
      subnet_id: config.subnetId || null,
      user_data: config.userData || null,
      ami_id: config.amiId || null,
      ami_type: config.amiType || 'auto',
    }),
  });
}

export function deployStream(config: AwsConfig & { accountId: string }) {
  const sessionId = getSessionId();
  const params = new URLSearchParams({
    region: config.region,
    account_id: config.accountId,
    repository: config.ecrRepository,
    instance_type: config.instanceType,
    security_group: "",  // Will use default automatically
    volume_size: String(config.volumeSize),
    volume_type: config.volumeType || 'gp3',
  });
  
  if (config.availabilityZone) {
    params.append('availability_zone', config.availabilityZone);
  }
  if (config.subnetId) {
    params.append('subnet_id', config.subnetId);
  }
  if (config.userData) {
    params.append('user_data', config.userData);
  }
  if (config.amiId) {
    params.append('ami_id', config.amiId);
  }
  params.append('ami_type', config.amiType || 'auto');
  
  // EventSource doesn't support custom headers, so we'll pass session_id as a param
  // Backend will need to handle this
  if (sessionId) {
    params.append('session_id', sessionId);
  }
  
  return new EventSource(`${API_BASE}/deploy/stream?${params.toString()}`);
}

export function terminate(region: string, instanceId: string) {
  // Session ID is automatically included via apiFetch
  return apiFetch<{ status: string }>("/terminate", {
    method: "POST",
    body: JSON.stringify({ profile: "", region, instance_id: instanceId }),
  });
}

export function connect(
  region: string,
  instanceId: string,
  keyPath?: string,
  launchTerminal: boolean = true,
) {
  // Session ID is automatically included via apiFetch
  return apiFetch<{ status: string; sshCommand: string; publicDns: string; launched?: boolean; launchError?: string }>("/connect", {
    method: "POST",
    body: JSON.stringify({
      profile: "",
      region,
      instance_id: instanceId,
      key_path: keyPath,
      launch_terminal: launchTerminal,
    }),
  });
}

export function uploadFile(
  region: string,
  instanceId: string,
  localPath: string,
  destinationPath: string,
  keyPath?: string,
) {
  // Session ID is automatically included via apiFetch
  return apiFetch<{ status: string; message?: string }>("/upload", {
    method: "POST",
    body: JSON.stringify({
      profile: "",
      region,
      instance_id: instanceId,
      local_path: localPath,
      destination_path: destinationPath,
      key_path: keyPath,
    }),
  });
}

export async function downloadFile(
  region: string,
  instanceId: string,
  remotePath: string,
  containerName?: string,
  repository?: string,
  accountId?: string,
) {
  const sessionId = getSessionId();
  const headers: HeadersInit = { "Content-Type": "application/json" };
  
  if (sessionId) {
    headers["X-Session-ID"] = sessionId;
  }

  const response = await fetch(`${API_BASE}/download`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      profile: "",
      region,
      instance_id: instanceId,
      remote_path: remotePath,
      local_path: "", // Not used anymore - file is returned directly
      container_name: containerName,
      repository: repository,
      account_id: accountId,
    }),
  });

  if (!response.ok) {
    const detail = await response.text();
    
    // Check for session expiration (401 status or session-related errors)
    if (response.status === 401 || detail.includes('Invalid or expired session') || detail.includes('Session expired')) {
      // Clear expired session
      localStorage.removeItem('aws_session_id');
      // Throw a specific error that can be caught by components
      const sessionError = new Error('SESSION_EXPIRED');
      (sessionError as any).isSessionExpired = true;
      (sessionError as any).originalMessage = detail;
      throw sessionError;
    }
    
    throw new Error(detail || response.statusText);
  }

  // Get filename from Content-Disposition header or use remote path
  const contentDisposition = response.headers.get('Content-Disposition');
  let filename = remotePath.split('/').pop() || 'download';
  if (contentDisposition) {
    const filenameMatch = contentDisposition.match(/filename="?(.+?)"?$/);
    if (filenameMatch) {
      filename = filenameMatch[1];
    }
  }

  // Create blob and trigger download
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(a);

  return { status: "ok", message: `Downloaded ${filename}` };
}

export interface FileItem {
  name: string;
  path: string;
  isDirectory: boolean;
  size: number;
  permissions: string;
}

export function listFiles(
  region: string,
  instanceId: string,
  path: string = "/",
  containerName?: string,
  repository?: string,
  accountId?: string,
) {
  // Session ID is automatically included via apiFetch
  return apiFetch<{
    status: string;
    path: string;
    containerName?: string;
    files: FileItem[];
  }>("/list-files", {
    method: "POST",
    body: JSON.stringify({
      profile: "",
      region,
      instance_id: instanceId,
      path: path,
      container_name: containerName,
      repository: repository,
      account_id: accountId,
    }),
  });
}

export interface ContainerLogsResponse {
  status: string;
  containerName: string;
  logs: string;
  isRunning: boolean;
  containerStatus: string;
  lineCount: number;
}

export function getContainerLogs(
  region: string,
  instanceId: string,
  tail: number = 100,
  containerName?: string,
  repository?: string,
  accountId?: string,
) {
  // Session ID is automatically included via apiFetch
  return apiFetch<ContainerLogsResponse>("/container-logs", {
    method: "POST",
    body: JSON.stringify({
      profile: "",
      region,
      instance_id: instanceId,
      container_name: containerName,
      repository: repository,
      account_id: accountId,
      tail: tail,
      follow: false,
    }),
  });
}

export async function downloadContainerLogs(
  region: string,
  instanceId: string,
  tail: number = 10000,
  containerName?: string,
  repository?: string,
  accountId?: string,
) {
  const sessionId = getSessionId();
  const headers: HeadersInit = { "Content-Type": "application/json" };
  
  if (sessionId) {
    headers["X-Session-ID"] = sessionId;
  }

  const response = await fetch(`${API_BASE}/container-logs/download`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      profile: "",
      region,
      instance_id: instanceId,
      container_name: containerName,
      repository: repository,
      account_id: accountId,
      tail: tail,
      follow: false,
    }),
  });

  if (!response.ok) {
    const detail = await response.text();
    
    // Check for session expiration
    if (response.status === 401 || detail.includes('Invalid or expired session') || detail.includes('Session expired')) {
      localStorage.removeItem('aws_session_id');
      const sessionError = new Error('SESSION_EXPIRED');
      (sessionError as any).isSessionExpired = true;
      (sessionError as any).originalMessage = detail;
      throw sessionError;
    }
    
    throw new Error(detail || response.statusText);
  }

  // Get filename from Content-Disposition header
  const contentDisposition = response.headers.get('Content-Disposition');
  let filename = `container_logs_${Date.now()}.log`;
  if (contentDisposition) {
    const filenameMatch = contentDisposition.match(/filename="?(.+?)"?$/);
    if (filenameMatch) {
      filename = filenameMatch[1];
    }
  }

  // Create blob and trigger download
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(a);

  return { status: "ok", message: `Downloaded logs as ${filename}` };
}

