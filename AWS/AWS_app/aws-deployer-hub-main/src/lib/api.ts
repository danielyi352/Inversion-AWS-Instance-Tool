import type { AwsConfig, AwsMetadata, DeployResponse, RunningInstance, AssumeRoleLoginRequest, AssumeRoleLoginResponse } from "@/types/aws";

// Use a fixed local API base to avoid proxy/env drift during development.
const API_BASE = "http://127.0.0.1:8000/api";

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
      throw new Error(detail || res.statusText);
    }
    return res.json();
  } catch (error) {
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

export function assumeRoleLogin(request: AssumeRoleLoginRequest) {
  return apiFetch<AssumeRoleLoginResponse>("/auth/assume-role", {
    method: "POST",
    body: JSON.stringify({
      role_arn: request.roleArn,
      external_id: request.externalId,
      region: request.region,
      session_name: request.sessionName || "inversion-deployer-session",
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
  });
  
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

export function downloadFile(
  region: string,
  instanceId: string,
  remotePath: string,
  localPath: string,
  keyPath?: string,
) {
  // Session ID is automatically included via apiFetch
  return apiFetch<{ status: string; message?: string }>("/download", {
    method: "POST",
    body: JSON.stringify({
      profile: "",
      region,
      instance_id: instanceId,
      remote_path: remotePath,
      local_path: localPath,
      key_path: keyPath,
    }),
  });
}

