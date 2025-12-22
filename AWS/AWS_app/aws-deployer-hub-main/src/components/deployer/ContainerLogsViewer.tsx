import { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { 
  FileText, 
  Download, 
  RefreshCw,
  Loader2,
  Play,
  Square,
  Terminal,
  Send
} from 'lucide-react';
import { toast } from 'sonner';
import { getContainerLogs, downloadContainerLogs, executeCommand, type ContainerLogsResponse } from '@/lib/api';

interface ContainerLogsViewerProps {
  instanceId: string;
  region: string;
  accountId: string;
  repository: string;
  containerName?: string;
}

export function ContainerLogsViewer({
  instanceId,
  region,
  accountId,
  repository,
  containerName,
}: ContainerLogsViewerProps) {
  const [logs, setLogs] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [containerStatus, setContainerStatus] = useState<{ isRunning: boolean; status: string } | null>(null);
  const [tail, setTail] = useState(100);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState<NodeJS.Timeout | null>(null);
  
  // Terminal state
  const [command, setCommand] = useState('');
  const [terminalOutput, setTerminalOutput] = useState<string[]>([]);
  const [executing, setExecuting] = useState(false);
  const [executeOnHost, setExecuteOnHost] = useState(false);
  const terminalEndRef = useRef<HTMLDivElement>(null);

  const loadLogs = async () => {
    if (!instanceId) {
      toast.error('No instance selected');
      return;
    }

    // Prevent multiple simultaneous loads
    if (loading) {
      return;
    }

    setLoading(true);
    try {
      const result: ContainerLogsResponse = await getContainerLogs(
        region,
        instanceId,
        tail,
        containerName,
        repository,
        accountId
      );
      setLogs(result.logs || '');
      setContainerStatus({
        isRunning: result.isRunning,
        status: result.containerStatus
      });
    } catch (error) {
      // Check for session expiration
      if (error instanceof Error && (error as any).isSessionExpired) {
        toast.error('Your session has expired. Please login again.', {
          duration: 5000,
          action: {
            label: 'Reload',
            onClick: () => window.location.reload()
          }
        });
        return;
      }
      
      const errorMessage = error instanceof Error ? error.message : 'Failed to load logs';
      toast.error(`Failed to load logs: ${errorMessage}`);
      console.error('Load logs error:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (instanceId) {
      loadLogs();
    }
    
    // Cleanup on unmount
    return () => {
      if (refreshInterval) {
        clearInterval(refreshInterval);
      }
    };
  }, [instanceId, containerName, tail]);

  // Auto-refresh logic
  useEffect(() => {
    if (autoRefresh && instanceId) {
      const interval = setInterval(() => {
        loadLogs();
      }, 5000); // Refresh every 5 seconds
      setRefreshInterval(interval);
      
      return () => {
        clearInterval(interval);
      };
    } else {
      if (refreshInterval) {
        clearInterval(refreshInterval);
        setRefreshInterval(null);
      }
    }
  }, [autoRefresh, instanceId]);

  const handleDownload = async () => {
    if (downloading) {
      return;
    }

    setDownloading(true);
    try {
      await downloadContainerLogs(
        region,
        instanceId,
        10000, // Download up to 10k lines
        containerName,
        repository,
        accountId
      );
      toast.success('Logs downloaded successfully');
    } catch (error) {
      // Check for session expiration
      if (error instanceof Error && (error as any).isSessionExpired) {
        toast.error('Your session has expired. Please login again to download logs.', {
          duration: 5000,
          action: {
            label: 'Reload',
            onClick: () => window.location.reload()
          }
        });
        return;
      }
      
      const errorMessage = error instanceof Error ? error.message : 'Failed to download logs';
      toast.error(`Failed to download logs: ${errorMessage}`);
      console.error('Download logs error:', error);
    } finally {
      setDownloading(false);
    }
  };

  const handleRefresh = () => {
    loadLogs();
  };

  const toggleAutoRefresh = () => {
    setAutoRefresh(!autoRefresh);
  };

  // Terminal functions
  const executeTerminalCommand = async () => {
    if (!command.trim() || executing) {
      return;
    }

    setExecuting(true);
    const commandToExecute = command.trim();
    setCommand(''); // Clear input
    
    // Add command to output
    const prompt = executeOnHost ? '[host]' : (containerName ? `[${containerName}]` : '[host]');
    setTerminalOutput(prev => [...prev, `$ ${prompt} ${commandToExecute}`]);

    try {
      const result = await executeCommand(
        region,
        instanceId,
        commandToExecute,
        containerName,
        repository,
        accountId,
        executeOnHost
      );

      // Add output to terminal
      if (result.combined) {
        setTerminalOutput(prev => [...prev, result.combined]);
      } else if (result.stdout) {
        setTerminalOutput(prev => [...prev, result.stdout]);
      }
      
      if (result.stderr && result.stderr !== result.stdout) {
        setTerminalOutput(prev => [...prev, `[stderr] ${result.stderr}`]);
      }

      // Scroll to bottom
      setTimeout(() => {
        terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
      }, 100);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to execute command';
      setTerminalOutput(prev => [...prev, `[error] ${errorMessage}`]);
      toast.error(`Command failed: ${errorMessage}`);
    } finally {
      setExecuting(false);
    }
  };

  const handleTerminalKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      executeTerminalCommand();
    }
  };

  const clearTerminal = () => {
    setTerminalOutput([]);
  };

  // Auto-scroll terminal output
  useEffect(() => {
    if (terminalOutput.length > 0) {
      terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [terminalOutput]);

  return (
    <Card className="border-border/60 shadow-sm">
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base font-medium">
            <FileText className="h-4 w-4" />
            Container Console
            {containerName && (
              <span className="text-sm font-normal text-muted-foreground">
                ({containerName})
              </span>
            )}
            {containerStatus && (
              <span className={`text-xs font-normal px-2 py-1 rounded ${
                containerStatus.isRunning 
                  ? 'bg-green-100 dark:bg-green-900/20 text-green-700 dark:text-green-400' 
                  : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-400'
              }`}>
                {containerStatus.isRunning ? 'Running' : 'Stopped'}
              </span>
            )}
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="logs" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="logs">
              <FileText className="h-4 w-4 mr-2" />
              Logs
            </TabsTrigger>
            <TabsTrigger value="terminal">
              <Terminal className="h-4 w-4 mr-2" />
              Terminal
            </TabsTrigger>
          </TabsList>
          
          <TabsContent value="logs" className="space-y-4 mt-4">
            <div className="flex items-center justify-end gap-2">
              <div className="flex items-center gap-2">
                <label className="text-xs text-muted-foreground">Lines:</label>
                <input
                  type="number"
                  min="10"
                  max="10000"
                  value={tail}
                  onChange={(e) => setTail(Math.max(10, Math.min(10000, parseInt(e.target.value) || 100)))}
                  className="w-20 px-2 py-1 text-xs border border-border/60 rounded bg-background"
                  disabled={loading}
                />
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={toggleAutoRefresh}
                disabled={loading || !containerStatus?.isRunning}
                className={`border-border/60 ${autoRefresh ? 'bg-blue-50 dark:bg-blue-900/20' : ''}`}
                title={containerStatus?.isRunning ? 'Auto-refresh logs every 5 seconds' : 'Container must be running for auto-refresh'}
              >
                {autoRefresh ? (
                  <Square className="h-4 w-4" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleRefresh}
                disabled={loading}
                className="border-border/60"
              >
                <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleDownload}
                disabled={downloading || !logs}
                className="border-border/60"
              >
                {downloading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
              </Button>
            </div>
            
            {/* Logs Display */}
            <div className="border border-border/60 rounded-md bg-black text-green-400 font-mono text-xs p-4 min-h-[300px] max-h-[600px] overflow-y-auto">
              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  <span className="ml-2 text-muted-foreground">Loading logs...</span>
                </div>
              ) : logs ? (
                <pre className="whitespace-pre-wrap break-words">{logs}</pre>
              ) : (
                <div className="flex items-center justify-center py-12">
                  <span className="text-muted-foreground">No logs available</span>
                </div>
              )}
            </div>

            {/* Info */}
            <div className="text-xs text-muted-foreground flex items-center justify-between">
              <span>
                {logs.split('\n').length} {logs.split('\n').length === 1 ? 'line' : 'lines'}
                {containerName && ` • Container: ${containerName}`}
              </span>
              {autoRefresh && containerStatus?.isRunning && (
                <span className="text-blue-600 dark:text-blue-400">Auto-refreshing every 5 seconds...</span>
              )}
            </div>
          </TabsContent>

          <TabsContent value="terminal" className="space-y-4 mt-4">
            {/* Terminal Output */}
            <div className="border border-border/60 rounded-md bg-black text-green-400 font-mono text-xs p-4 min-h-[300px] max-h-[600px] overflow-y-auto">
              {terminalOutput.length === 0 ? (
                <div className="flex items-center justify-center py-12">
                  <span className="text-muted-foreground">Terminal ready. Type a command and press Enter.</span>
                </div>
              ) : (
                <div className="space-y-1">
                  {terminalOutput.map((line, index) => (
                    <div key={index} className="whitespace-pre-wrap break-words">
                      {line}
                    </div>
                  ))}
                  <div ref={terminalEndRef} />
                </div>
              )}
            </div>

            {/* Command Input */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Input
                  value={command}
                  onChange={(e) => setCommand(e.target.value)}
                  onKeyPress={handleTerminalKeyPress}
                  placeholder={executeOnHost ? "Execute command on host..." : (containerName ? `Execute command in ${containerName}...` : "Execute command on host...")}
                  disabled={executing}
                  className="font-mono text-sm"
                />
                <Button
                  onClick={executeTerminalCommand}
                  disabled={executing || !command.trim()}
                  size="sm"
                  className="gap-2"
                >
                  {executing ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )}
                  Execute
                </Button>
                <Button
                  variant="outline"
                  onClick={clearTerminal}
                  disabled={terminalOutput.length === 0}
                  size="sm"
                >
                  Clear
                </Button>
              </div>
              {containerName && (
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="executeOnHost"
                    checked={executeOnHost}
                    onChange={(e) => setExecuteOnHost(e.target.checked)}
                    className="rounded border-border"
                  />
                  <label htmlFor="executeOnHost" className="text-xs text-muted-foreground cursor-pointer">
                    Execute on host (instead of container)
                  </label>
                </div>
              )}
            </div>

            {/* Info */}
            <div className="text-xs text-muted-foreground">
              {executeOnHost 
                ? 'Commands will execute on the EC2 host instance'
                : (containerName 
                  ? `Commands will execute inside container: ${containerName}`
                  : 'Commands will execute on the EC2 host instance')}
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

