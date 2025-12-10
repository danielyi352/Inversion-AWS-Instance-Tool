import type { AwsConfig, AwsMetadata, DeployResponse, RunningInstance } from "@/types/aws";

// Use a fixed local API base to avoid proxy/env drift during development.
const API_BASE = "http://127.0.0.1:8000/api";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || res.statusText);
  }
  return res.json();
}

export function loginSso(profile: string, region: string) {
  return apiFetch<{ status: string; message: string }>("/sso/login", {
    method: "POST",
    body: JSON.stringify({ profile, region }),
  });
}

export function fetchMetadata(profile: string, region: string) {
  return apiFetch<AwsMetadata>(`/metadata?profile=${encodeURIComponent(profile)}&region=${encodeURIComponent(region)}`);
}

export function fetchInstances(profile: string, region: string) {
  return apiFetch<{ instances: RunningInstance[] }>(
    `/instances?profile=${encodeURIComponent(profile)}&region=${encodeURIComponent(region)}`
  );
}

export function deploy(config: AwsConfig & { accountId: string }) {
  return apiFetch<DeployResponse>("/deploy", {
    method: "POST",
    body: JSON.stringify({
      profile: config.profile,
      region: config.region,
      account_id: config.accountId,
      repository: config.ecrRepository,
      instance_type: config.instanceType,
      key_pair: config.keyPair,
      security_group: config.securityGroup,
      volume_size: config.volumeSize,
    }),
  });
}

export function deployStream(config: AwsConfig & { accountId: string }) {
  const params = new URLSearchParams({
    profile: config.profile,
    region: config.region,
    account_id: config.accountId,
    repository: config.ecrRepository,
    instance_type: config.instanceType,
    key_pair: config.keyPair,
    security_group: config.securityGroup,
    volume_size: String(config.volumeSize),
  });
  return new EventSource(`${API_BASE}/deploy/stream?${params.toString()}`);
}

export function terminate(profile: string, region: string, instanceId: string) {
  return apiFetch<{ status: string }>("/terminate", {
    method: "POST",
    body: JSON.stringify({ profile, region, instance_id: instanceId }),
  });
}

export function connect(
  profile: string,
  region: string,
  instanceId: string,
  keyPath?: string,
  launchTerminal: boolean = true,
) {
  return apiFetch<{ status: string; sshCommand: string; publicDns: string; launched?: boolean; launchError?: string }>("/connect", {
    method: "POST",
    body: JSON.stringify({
      profile,
      region,
      instance_id: instanceId,
      key_path: keyPath,
      launch_terminal: launchTerminal,
    }),
  });
}

export function uploadFile(
  profile: string,
  region: string,
  instanceId: string,
  localPath: string,
  destinationPath: string,
  keyPath?: string,
) {
  return apiFetch<{ status: string; message?: string }>("/upload", {
    method: "POST",
    body: JSON.stringify({
      profile,
      region,
      instance_id: instanceId,
      local_path: localPath,
      destination_path: destinationPath,
      key_path: keyPath,
    }),
  });
}

export function downloadFile(
  profile: string,
  region: string,
  instanceId: string,
  remotePath: string,
  localPath: string,
  keyPath?: string,
) {
  return apiFetch<{ status: string; message?: string }>("/download", {
    method: "POST",
    body: JSON.stringify({
      profile,
      region,
      instance_id: instanceId,
      remote_path: remotePath,
      local_path: localPath,
      key_path: keyPath,
    }),
  });
}

