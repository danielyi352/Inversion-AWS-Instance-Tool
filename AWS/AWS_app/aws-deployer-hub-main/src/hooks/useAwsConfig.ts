import { useState, useEffect } from 'react';
import type { AwsConfig, RunningInstance, LogEntry, TransferStatus, AwsMetadata } from '@/types/aws';
import { connect, deployStream, downloadFile, fetchInstances, fetchMetadata, loginSso, terminate, uploadFile } from '@/lib/api';

const STORAGE_KEY = 'inversion-deployer-config';

const defaultConfig: AwsConfig = {
  profile: '',
  region: 'us-east-1',
  accountId: '',
  ecrRepository: '',
  instanceType: 't3.medium',
  keyPair: '',
  securityGroup: 'default',
  volumeSize: 30,
};

export function useAwsConfig() {
  const [config, setConfig] = useState<AwsConfig>(defaultConfig);
  const [rememberSettings, setRememberSettings] = useState(true);
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [instances, setInstances] = useState<RunningInstance[]>([]);
  const [selectedInstance, setSelectedInstance] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [progress, setProgress] = useState(0);
  const [metadata, setMetadata] = useState<AwsMetadata>({
    repositories: [],
    keyPairs: [],
    securityGroups: [],
  });
  const [transferStatus, setTransferStatus] = useState<TransferStatus>({
    progress: 0,
    isUploading: false,
    isDownloading: false,
    currentFile: '',
  });
  const [deploySource, setDeploySource] = useState<EventSource | null>(null);

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
    try {
      addLog('Refreshing AWS data...', 'info');
      setProgress(20);
      const meta = await fetchMetadata(config.profile || 'default', config.region);
      setMetadata(meta);
      setProgress(50);
      const { instances: running } = await fetchInstances(config.profile || 'default', config.region);
      setInstances(running);
      addLog('AWS data refreshed', 'success');
      setProgress(100);
    } catch (err) {
      addLog(`Refresh failed: ${String(err)}`, 'error');
    } finally {
      setTimeout(() => setProgress(0), 400);
    }
  };

  const handleDeploy = async () => {
    if (!isLoggedIn) {
      addLog('Please log in via AWS SSO first', 'error');
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
      await terminate(config.profile || 'default', config.region, selectedInstance);
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

    connect(config.profile || 'default', config.region, selectedInstance, derivedKeyPath)
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
        config.profile || 'default',
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
        config.profile || 'default',
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
    handleSsoLogin,
    handleRefresh,
    handleDeploy,
    handleTerminate,
    handleConnect,
    handleUpload,
    handleDownload,
  };
}
