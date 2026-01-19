import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import type { AwsConfig, RunningInstance, LogEntry, TransferStatus, AwsMetadata } from '@/types/aws';
import { assumeRoleLogin, checkRepositoryStatus, connect, deployStream, downloadFile, fetchInstances, fetchMetadata, loginSso, terminate, uploadFile, listOrganizations } from '@/lib/api';
import { toast } from 'sonner';

const STORAGE_KEY = 'inversion-deployer-config';

const defaultConfig: AwsConfig = {
  region: 'us-east-1',
  accountId: '',
  ecrRepository: '',
  instanceType: 't3.medium',
  volumeSize: 30,
  volumeType: 'gp3',
  availabilityZone: '',
  subnetId: '',
  userData: '',
  amiType: 'auto',
  amiId: '',
};

export function useAwsConfig() {
  const navigate = useNavigate();
  const [config, setConfig] = useState<AwsConfig>(defaultConfig);
  const [rememberSettings, setRememberSettings] = useState(true);
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [instances, setInstances] = useState<RunningInstance[]>([]);
  const [selectedInstance, setSelectedInstance] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [progress, setProgress] = useState(0);
  const [metadata, setMetadata] = useState<AwsMetadata>({
    repositories: [],
    securityGroups: [],
  });
  const [transferStatus, setTransferStatus] = useState<TransferStatus>({
    progress: 0,
    isUploading: false,
    isDownloading: false,
    currentFile: '',
  });
  const [deploySource, setDeploySource] = useState<EventSource | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [repositoryStatus, setRepositoryStatus] = useState<{
    exists: boolean;
    hasImages: boolean;
    imageCount: number;
    images: Array<{imageTag: string; imageDigest: string}>;
    repositoryUri?: string;
    message: string;
  } | null>(null);
  const [orgId, setOrgId] = useState<string | null>(null);

  // Load user's organization
  useEffect(() => {
    listOrganizations()
      .then((response) => {
        if (response.organizations && response.organizations.length > 0) {
          // Use the user's owned org if they own one, otherwise use the first org
          const ownedOrg = response.organizations.find((org: any) => org.role === 'owner');
          setOrgId(ownedOrg?.org_id || response.organizations[0].org_id);
        }
      })
      .catch(() => {
        // Ignore errors - user might not be in an org yet
      });
  }, []);

  // Check for existing session on load
  useEffect(() => {
    const sessionId = localStorage.getItem('aws_session_id');
    if (sessionId) {
      setIsLoggedIn(true);
      // Try to refresh to verify session is still valid
      handleRefresh().catch(() => {
        // Session expired, clear it
        localStorage.removeItem('aws_session_id');
        setIsLoggedIn(false);
      });
    }
  }, []);

  // Load saved settings
  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        setConfig(parsed.config || defaultConfig);
        setRememberSettings(parsed.rememberSettings ?? true);
      } catch {
        console.error('Failed to parse saved settings');
      }
    }
  }, []);

  // Save settings when changed
  useEffect(() => {
    if (rememberSettings) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ config, rememberSettings }));
    }
  }, [config, rememberSettings]);

  const updateConfig = (updates: Partial<AwsConfig>) => {
    setConfig(prev => ({ ...prev, ...updates }));
  };

  const addLog = (message: string, type: LogEntry['type'] = 'info') => {
    const timestamp = new Date().toISOString();
    setLogs(prev => [...prev, { timestamp, message, type }]);
  };

  const clearLogs = () => setLogs([]);

  const handleRoleLogin = async (roleArn: string, accountId: string, externalId: string, region: string) => {
    if (!orgId) {
      const errorMsg = 'Organization ID is required. Please ensure you are a member of an organization.';
      addLog(errorMsg, 'error');
      toast.error(errorMsg);
      throw new Error(errorMsg);
    }

    try {
      addLog('Connecting to AWS account...', 'info');
      setProgress(15);
      const response = await assumeRoleLogin({
        roleArn,
        accountId,
        externalId: externalId || undefined,
        region,
        orgId,
      });
      
      // Store session ID
      localStorage.setItem('aws_session_id', response.session_id);
      
      // Update config with account ID and region from response
      updateConfig({ 
        accountId: response.account_id,
        region: region 
      });
      
      // Save account ID to config for future use
      if (rememberSettings) {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
          try {
            const parsed = JSON.parse(saved);
            parsed.config = { ...parsed.config, accountId: response.account_id, region: region };
            localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
          } catch {
            // Ignore parse errors
          }
        }
      }
      
      setProgress(60);
      setIsLoggedIn(true);
      addLog(`Login successful! Connected to account ${response.account_id}`, 'success');
      setProgress(100);
      await handleRefresh();
    } catch (err) {
      addLog(`Login failed: ${String(err)}`, 'error');
      throw err; // Re-throw so dialog can show error
    } finally {
      setTimeout(() => setProgress(0), 500);
    }
  };

  const handleSsoLogin = async () => {
    try {
      addLog('Initiating AWS SSO login...', 'info');
      setProgress(15);
      await loginSso(config.profile || 'default', config.region);
      setProgress(60);
      setIsLoggedIn(true);
      addLog('AWS SSO login successful', 'success');
      await handleRefresh();
    } catch (err) {
      addLog(`SSO login failed: ${String(err)}`, 'error');
    } finally {
      setProgress(0);
    }
  };

  const handleRefresh = async () => {
    if (isRefreshing) {
      return; // Prevent multiple simultaneous refreshes
    }
    
    try {
      setIsRefreshing(true);
      // Check if we have a session ID
      const sessionId = localStorage.getItem('aws_session_id');
      if (!sessionId) {
        addLog('Not logged in. Please login first.', 'error');
        setIsLoggedIn(false);
        return;
      }
      
      addLog('Refreshing AWS data...', 'info');
      setProgress(20);
      const meta = await fetchMetadata(config.region);
      setMetadata(meta);
      setProgress(50);
      const { instances: running } = await fetchInstances(config.region);
      setInstances(running);
      addLog('AWS data refreshed', 'success');
      setProgress(100);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      addLog(`Refresh failed: ${errorMessage}`, 'error');
      
      // Check for specific error types
      if (errorMessage.includes('Cannot connect to backend')) {
        addLog('Backend server is not running. Please start it and try again.', 'error');
      } else if (errorMessage.includes('Session expired') || errorMessage.includes('Invalid or expired session')) {
        addLog('Session expired. Please login again.', 'error');
        localStorage.removeItem('aws_session_id');
        setIsLoggedIn(false);
      } else if (errorMessage.includes('Failed to fetch')) {
        addLog('Cannot reach backend server. Is it running on port 8000?', 'error');
      }
    } finally {
      setIsRefreshing(false);
      setTimeout(() => setProgress(0), 400);
    }
  };

  const handleConnectRepository = async (repository: string, region: string) => {
    if (!repository) {
      setRepositoryStatus(null);
      return {
        exists: false,
        hasImages: false,
        imageCount: 0,
        images: [],
        message: '',
      };
    }

    try {
      const status = await checkRepositoryStatus(repository, region);
      setRepositoryStatus(status);
      
      if (!status.exists) {
        toast.error(`Repository '${repository}' not found`);
        addLog(`Repository '${repository}' not found`, 'error');
      } else if (!status.hasImages) {
        toast.warning('Repository is empty. Please push an image first.');
        addLog('Repository is empty. Please push an image first.', 'warning');
      } else {
        toast.success(`Repository connected! Found ${status.imageCount} image(s)`);
        addLog(`Repository connected! Found ${status.imageCount} image(s)`, 'success');
      }
      
      return status;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(`Failed to check repository: ${errorMessage}`);
      addLog(`Failed to check repository: ${errorMessage}`, 'error');
      setRepositoryStatus(null);
      throw error;
    }
  };

  const handleDeploy = async () => {
    if (!isLoggedIn) {
      addLog('Please log in first', 'error');
      return;
    }
    if (deploySource) {
      deploySource.close();
    }
    addLog('Starting deployment...', 'info');
    setProgress(5);
    const source = deployStream(config);
    setDeploySource(source);

    source.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        addLog(String(data), 'info');
      } catch {
        addLog(evt.data, 'info');
      }
    };

    source.addEventListener('log', (evt) => {
      const data = (evt as MessageEvent).data;
      addLog(data, 'info');
    });

    source.addEventListener('progress', (evt) => {
      const data = Number((evt as MessageEvent).data);
      if (!Number.isNaN(data)) {
        setProgress(data);
      }
    });

    source.addEventListener('error', (evt) => {
      addLog(`Deployment failed: ${(evt as MessageEvent).data || 'stream error'}`, 'error');
      setProgress(0);
      source.close();
      setDeploySource(null);
    });

    source.addEventListener('complete', (evt) => {
      try {
        const payload = JSON.parse((evt as MessageEvent).data);
        if (payload.instance) {
          const newInstance: RunningInstance = {
            id: payload.instance.id,
            name: `${config.profile}-${config.ecrRepository || 'repo'}-container`,
            status: 'running',
            publicDns: payload.instance.publicDns,
            instanceType: payload.instance.instanceType,
            launchTime: new Date().toISOString(),
          };
          setInstances(prev => [...prev, newInstance]);
          setSelectedInstance(newInstance.id);
          addLog(`Deployment complete! Instance ID: ${newInstance.id}`, 'success');
        }
      } catch (e) {
        addLog(`Deployment complete but parsing failed: ${String(e)}`, 'warning');
      } finally {
        setProgress(100);
        setTimeout(() => setProgress(0), 500);
        source.close();
        setDeploySource(null);
      }
    });
  };

  const handleTerminate = async () => {
    if (!selectedInstance) {
      addLog('Please select an instance to terminate', 'error');
      return;
    }
    try {
      addLog(`Terminating instance ${selectedInstance}...`, 'warning');
      setProgress(40);
      await terminate(config.region, selectedInstance);
      setInstances(prev => prev.filter(i => i.id !== selectedInstance));
      setSelectedInstance(null);
      setProgress(100);
      addLog('Instance terminated', 'success');
    } catch (err) {
      addLog(`Terminate failed: ${String(err)}`, 'error');
    } finally {
      setTimeout(() => setProgress(0), 500);
    }
  };

  const handleConnect = () => {
    if (!selectedInstance) {
      addLog('Please select an instance to connect', 'error');
      return;
    }
    const derivedKeyPath =
      config.keyPair ? `~/.ssh/${config.keyPair}.pem` : undefined;

    connect(config.region, selectedInstance, derivedKeyPath)
      .then(resp => {
        addLog('SSH command:', 'info');
        addLog(resp.sshCommand, 'success');
        if (resp.launched) {
          addLog('Opened macOS Terminal with SSH session.', 'success');
        } else if (resp.launchError) {
          addLog(`Terminal launch failed: ${resp.launchError}`, 'warning');
        }
      })
      .catch(err => addLog(`Connect failed: ${String(err)}`, 'error'));
  };

  const handleUpload = async (file: string, destination: string) => {
    if (!selectedInstance) {
      addLog('No instance selected for upload', 'error');
      return;
    }
    try {
      setTransferStatus(prev => ({ ...prev, isUploading: true, currentFile: file }));
      addLog(`Uploading ${file} -> ${destination}`, 'info');
      const resp = await uploadFile(
        config.region,
        selectedInstance,
        file,
        destination,
      );
      addLog(resp.message || 'Upload complete.', 'success');
    } catch (err) {
      addLog(`Upload failed: ${String(err)}`, 'error');
    } finally {
      setTransferStatus(prev => ({ ...prev, isUploading: false, currentFile: '' }));
    }
  };

  const handleDownload = async (remotePath: string, localPath: string) => {
    if (!selectedInstance) {
      addLog('No instance selected for download', 'error');
      return;
    }
    try {
      setTransferStatus(prev => ({ ...prev, isDownloading: true, currentFile: remotePath }));
      addLog(`Downloading ${remotePath} -> ${localPath || 'local destination'}`, 'info');
      const resp = await downloadFile(
        config.region,
        selectedInstance,
        remotePath,
        localPath,
      );
      addLog(resp.message || 'Download complete.', 'success');
    } catch (err) {
      addLog(`Download failed: ${String(err)}`, 'error');
    } finally {
      setTransferStatus(prev => ({ ...prev, isDownloading: false, currentFile: '' }));
    }
  };

  const handleLogout = async () => {
    // Logout from user session (Google OAuth)
    try {
      const { logout } = await import('@/lib/api');
      await logout();
    } catch (err) {
      console.error('Failed to logout user session:', err);
    }
    
    // Close any active deployment streams
    if (deploySource) {
      deploySource.close();
      setDeploySource(null);
    }
    
    // Clear AWS session
    localStorage.removeItem('aws_session_id');
    localStorage.removeItem('user_session_id');
    setIsLoggedIn(false);
    
    // Clear state
    setInstances([]);
    setSelectedInstance(null);
    setMetadata({ repositories: [], securityGroups: [] });
    setRepositoryStatus(null);
    
    // Redirect to login page using React Router
    navigate('/login', { replace: true });
    setProgress(0);
    
    addLog('Logged out successfully', 'info');
  };

  const clearRepositoryStatus = () => {
    setRepositoryStatus(null);
  };

  return {
    config,
    updateConfig,
    rememberSettings,
    setRememberSettings,
    isLoggedIn,
    instances,
    selectedInstance,
    setSelectedInstance,
    logs,
    addLog,
    clearLogs,
    progress,
    metadata,
    transferStatus,
    setTransferStatus,
    repositoryStatus,
    clearRepositoryStatus,
    isRefreshing,
    handleRoleLogin,
    handleSsoLogin,
    handleRefresh,
    handleConnectRepository,
    handleDeploy,
    handleTerminate,
    handleConnect,
    handleUpload,
    handleDownload,
    handleLogout,
  };
}
