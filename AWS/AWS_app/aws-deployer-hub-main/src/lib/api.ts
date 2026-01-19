import type { AwsConfig, AwsMetadata, DeployResponse, RunningInstance, AssumeRoleLoginRequest, AssumeRoleLoginResponse } from "@/types/aws";

// Use environment variable for API base URL, fallback to local for development
const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api";

// Get AWS session ID from localStorage (for AWS role assumption)
function getSessionId(): string | null {
  return localStorage.getItem('aws_session_id');
}

// Get user session ID from localStorage (for user authentication)
function getUserSessionId(): string | null {
  return localStorage.getItem('user_session_id');
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const sessionId = getSessionId();
  const userSessionId = getUserSessionId();
  const headers: HeadersInit = { "Content-Type": "application/json" };
  
  // Add AWS session ID to headers if available (for AWS role assumption)
  if (sessionId) {
    headers["X-Session-ID"] = sessionId;
  }
  
  // Add user session ID to headers if available (for user authentication)
  if (userSessionId) {
    headers["X-User-Session-ID"] = userSessionId;
  }
  
  // Merge with any existing headers from options
  const mergedHeaders = {
    ...headers,
    ...(options?.headers || {}),
  };
  
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: mergedHeaders,
    });
    
    if (!res.ok) {
      let detail: string;
      try {
        const errorData = await res.json();
        detail = errorData.detail || errorData.message || JSON.stringify(errorData);
      } catch {
        detail = await res.text() || res.statusText;
      }
      
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

export function googleLogin(token: string) {
  return apiFetch<{
    status: string;
    session_id: string;
    user: {
      user_id: string;
      email: string;
      name: string | null;
    };
    expires_at: string;
    message: string;
  }>("/auth/google/login", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export function getCurrentUser() {
  const userSessionId = getUserSessionId();
  if (!userSessionId) {
    return Promise.reject(new Error("Not authenticated"));
  }
  
  return fetch(`${API_BASE}/auth/me`, {
    headers: {
      "X-User-Session-ID": userSessionId,
    },
  }).then(async (res) => {
    if (!res.ok) {
      throw new Error("Not authenticated");
    }
    return res.json();
  });
}

export function checkAwsAccount(accountId: string) {
  const userSessionId = getUserSessionId();
  if (!userSessionId) {
    return Promise.reject(new Error("Not authenticated"));
  }
  
  return apiFetch<{
    account_id: string;
    is_associated: boolean;
    associated_with_other_user: boolean;
    associated_with_current_user?: boolean;
    other_user_email?: string;
    message: string;
  }>(`/auth/check-aws-account/${accountId}`, {
    method: "GET",
  });
}

export function logout() {
  const userSessionId = getUserSessionId();
  if (!userSessionId) {
    return Promise.resolve({ status: "ok" });
  }
  
  return fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    headers: {
      "X-User-Session-ID": userSessionId,
    },
  }).then(async (res) => {
    localStorage.removeItem('user_session_id');
    return res.json();
  });
}

export function cloudformationLogin(accountId: string, region: string, orgId: string) {
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
      org_id: orgId,
    }),
  });
}

export function cloudformationVerify(accountId: string, region: string, orgId: string) {
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
      org_id: orgId,
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
      org_id: request.orgId,
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

export function buildImageWithCodeBuild(
  repository: string,
  sourceCode: File,
  imageTag: string = "latest",
  region: string = "us-east-1",
  dockerfilePath: string = "Dockerfile"
) {
  const sessionId = getSessionId();
  const formData = new FormData();
  formData.append('repository', repository);
  formData.append('image_tag', imageTag);
  formData.append('region', region);
  formData.append('dockerfile_path', dockerfilePath);
  formData.append('source_code', sourceCode);

  const headers: HeadersInit = {};
  if (sessionId) {
    headers['X-Session-ID'] = sessionId;
  }

  return fetch(`${API_BASE}/ecr/build-image`, {
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

export function getBuildStatus(
  buildId: string,
  region: string = "us-east-1"
) {
  return apiFetch<{
    status: string;
    build_id: string;
    build_status: string;
    build_phase: string;
    build_complete: boolean;
    start_time: string | null;
    end_time: string | null;
    logs: {
      group_name?: string;
      stream_name?: string;
      deep_link?: string;
    };
    image_uri: string | null;
    error_info?: {
      failed_phase?: string;
      phase_context?: any[];
    };
    error_message?: string;
    build_number?: number;
  }>(`/ecr/build-status/${encodeURIComponent(buildId)}?region=${encodeURIComponent(region)}`);
}

export function getBuildLogs(
  buildId: string,
  region: string = "us-east-1",
  limit: number = 1000
) {
  return apiFetch<{
    status: string;
    logs: string;
    log_group?: string;
    log_stream?: string;
    event_count?: number;
    message?: string;
  }>(`/ecr/build-logs/${encodeURIComponent(buildId)}?region=${encodeURIComponent(region)}&limit=${limit}`);
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

export interface ExecuteCommandResponse {
  status: string;
  command: string;
  container_name?: string;
  exit_code: number;
  stdout: string;
  stderr: string;
  combined: string;
}

export async function executeCommand(
  region: string,
  instanceId: string,
  command: string,
  containerName?: string,
  repository?: string,
  accountId?: string,
  executeOnHost?: boolean,
): Promise<ExecuteCommandResponse> {
  const sessionId = getSessionId();
  const headers: HeadersInit = { "Content-Type": "application/json" };
  
  if (sessionId) {
    headers["X-Session-ID"] = sessionId;
  }

  const response = await fetch(`${API_BASE}/execute-command`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      profile: "",
      region,
      instance_id: instanceId,
      command: command,
      container_name: containerName,
      repository: repository,
      account_id: accountId,
      execute_on_host: executeOnHost || false,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

/**
 * Generate AWS Console Session Manager deep link URL.
 * Opens the AWS Console Session Manager page for the specified instance.
 * 
 * @param region AWS region (e.g., "us-east-1")
 * @param instanceId EC2 instance ID (e.g., "i-1234567890abcdef0")
 * @returns AWS Console URL that opens Session Manager for the instance
 */
export function getAwsConsoleSessionManagerUrl(region: string, instanceId: string) {
  return `https://${region}.console.aws.amazon.com/systems-manager/session-manager?region=${region}#/session-manager/instances/${instanceId}`;
}

/**
 * Open AWS Console Session Manager in a new tab.
 * This uses the AWS Console's built-in one-click browser-based shell.
 * 
 * Requirements:
 * - User must be logged into AWS Console
 * - User must have ssm:StartSession permission
 * - Instance must have AmazonSSMManagedInstanceCore policy attached
 * - SSM Agent must be running on the instance
 * 
 * @param region AWS region
 * @param instanceId EC2 instance ID
 */
export function openAwsConsoleTerminal(region: string, instanceId: string): void {
  const url = getAwsConsoleSessionManagerUrl(region, instanceId);
  window.open(url, '_blank', 'noopener,noreferrer');
}

// Deprecated: Keeping for backwards compatibility, but not used anymore
export interface TerminalStartResponse {
  terminal_session_id: string;
  aws_session_id: string;
  message: string;
}

// Deprecated: Use openAwsConsoleTerminal() instead
export function startTerminalSession(region: string, instanceId: string): Promise<TerminalStartResponse> {
  const sessionId = getSessionId();
  const headers: HeadersInit = { "Content-Type": "application/json" };
  
  if (sessionId) {
    headers["X-Session-ID"] = sessionId;
  }

  return apiFetch<TerminalStartResponse>("/terminal/start", {
    method: "POST",
    headers,
    body: JSON.stringify({
      region,
      instance_id: instanceId,
    }),
  });
}

// ============================================================================
// Organization API Functions
// ============================================================================

export interface CreateOrgRequest {
  name: string;
  slug?: string;
  description?: string;
}

export interface Organization {
  org_id: string;
  name: string;
  slug?: string;
  owner_id: string;
  description?: string;
  default_aws_account_id?: string;
  created_at: string;
  updated_at: string;
  role?: string; // When returned from list endpoint
}

export interface UpdateOrgRequest {
  name?: string;
  description?: string;
  default_aws_account_id?: string;
}

export interface OrganizationMember {
  user_id: string;
  email: string;
  name?: string;
  role: string;
  joined_at: string;
}

export interface InviteUserRequest {
  email: string;
  role: 'owner' | 'admin' | 'member';
}

export function createOrganization(data: CreateOrgRequest) {
  return apiFetch<{ status: string; organization: Organization; message: string }>("/orgs/create", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function listOrganizations() {
  return apiFetch<{ status: string; organizations: Organization[] }>("/orgs", {
    method: "GET",
  });
}

export function getOrganization(orgId: string) {
  return apiFetch<{ status: string; organization: Organization; member_count: number; aws_connection_count: number }>(`/orgs/${orgId}`, {
    method: "GET",
  });
}

export function updateOrganization(orgId: string, data: UpdateOrgRequest) {
  return apiFetch<{ status: string; organization: Organization; message: string }>(`/orgs/${orgId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function inviteUser(orgId: string, data: InviteUserRequest) {
  return apiFetch<{ status: string; invitation: any; message: string }>(`/orgs/${orgId}/invite`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function listOrgMembers(orgId: string) {
  return apiFetch<{ status: string; members: OrganizationMember[] }>(`/orgs/${orgId}/members`, {
    method: "GET",
  });
}

export function listInvitations() {
  return apiFetch<{ status: string; invitations: any[] }>("/orgs/invitations", {
    method: "GET",
  });
}

export function acceptInvitation(token: string) {
  return apiFetch<{ status: string; message: string }>(`/orgs/invitations/${token}/accept`, {
    method: "POST",
  });
}

export function rejectInvitation(token: string) {
  return apiFetch<{ status: string; message: string }>(`/orgs/invitations/${token}/reject`, {
    method: "POST",
  });
}

export function leaveOrganization(orgId: string) {
  return apiFetch<{ status: string; message: string }>(`/orgs/${orgId}/leave`, {
    method: "POST",
  });
}

export function updateMemberRole(orgId: string, userId: string, role: 'admin' | 'member') {
  return apiFetch<{ status: string; message: string }>(`/orgs/${orgId}/members/${userId}/role`, {
    method: "PUT",
    body: JSON.stringify({ user_id: userId, role }),
  });
}

export function removeMember(orgId: string, userId: string) {
  return apiFetch<{ status: string; message: string }>(`/orgs/${orgId}/members/${userId}`, {
    method: "DELETE",
  });
}

export function deleteOrganization(orgId: string) {
  const userSessionId = getUserSessionId();
  if (!userSessionId) {
    return Promise.reject(new Error("Not authenticated"));
  }
  
  return apiFetch<{ status: string; message: string }>(`/orgs/${orgId}`, {
    method: "DELETE",
  });
}
