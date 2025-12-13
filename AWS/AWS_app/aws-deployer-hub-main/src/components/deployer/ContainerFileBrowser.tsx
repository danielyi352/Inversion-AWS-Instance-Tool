import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { 
  Folder, 
  File, 
  Download, 
  ChevronLeft, 
  ChevronRight,
  RefreshCw,
  Loader2,
  FolderOpen
} from 'lucide-react';
import { toast } from 'sonner';
import { listFiles, downloadFile, type FileItem } from '@/lib/api';
import { formatBytes } from '@/lib/utils';

interface ContainerFileBrowserProps {
  instanceId: string;
  region: string;
  accountId: string;
  repository: string;
  containerName?: string;
}

export function ContainerFileBrowser({
  instanceId,
  region,
  accountId,
  repository,
  containerName,
}: ContainerFileBrowserProps) {
  const [currentPath, setCurrentPath] = useState<string>('/');
  const [files, setFiles] = useState<FileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [pathHistory, setPathHistory] = useState<string[]>(['/']);

  const loadFiles = async (path: string) => {
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
      const result = await listFiles(
        region,
        instanceId,
        path,
        containerName,
        repository,
        accountId
      );
      setFiles(result.files || []);
      setCurrentPath(result.path);
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
        // Don't break the UI - keep existing files visible
        console.error('Session expired:', error);
        return;
      }
      
      const errorMessage = error instanceof Error ? error.message : 'Failed to list files';
      toast.error(`Failed to list files: ${errorMessage}`);
      // Keep existing files if there was an error, don't clear them
      console.error('List files error:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (instanceId) {
      loadFiles(currentPath);
    }
  }, [instanceId, containerName]);

  const handleNavigate = (path: string) => {
    // Prevent navigation if already loading
    if (loading) {
      return;
    }
    
    // Add current path to history before navigating
    const newHistory = [...pathHistory];
    if (currentPath && !newHistory.includes(currentPath)) {
      newHistory.push(currentPath);
    }
    setPathHistory(newHistory);
    setCurrentPath(path);
    loadFiles(path);
  };

  const handleGoBack = () => {
    // Prevent navigation if already loading
    if (loading) {
      return;
    }
    
    if (pathHistory.length > 1) {
      const newHistory = [...pathHistory];
      newHistory.pop(); // Remove current path
      const previousPath = newHistory[newHistory.length - 1];
      setPathHistory(newHistory);
      setCurrentPath(previousPath);
      loadFiles(previousPath);
    } else {
      // Go to root
      setPathHistory(['/']);
      setCurrentPath('/');
      loadFiles('/');
    }
  };

  const handleDownload = async (file: FileItem) => {
    if (file.isDirectory) {
      handleNavigate(file.path);
      return;
    }

    // Prevent multiple simultaneous downloads
    if (downloading) {
      return;
    }

    setDownloading(file.path);
    try {
      await downloadFile(
        region,
        instanceId,
        file.path,
        containerName,
        repository,
        accountId
      );
      toast.success(`Downloaded ${file.name} successfully`);
    } catch (error) {
      // Check for session expiration
      if (error instanceof Error && (error as any).isSessionExpired) {
        toast.error('Your session has expired. Please login again to download files.', {
          duration: 5000,
          action: {
            label: 'Reload',
            onClick: () => window.location.reload()
          }
        });
        console.error('Session expired during download:', error);
        return;
      }
      
      const errorMessage = error instanceof Error ? error.message : 'Failed to download file';
      toast.error(`Failed to download ${file.name}: ${errorMessage}`);
      // Don't break the UI - just log the error
      console.error('Download error:', error);
    } finally {
      setDownloading(null);
    }
  };

  const handleRefresh = () => {
    loadFiles(currentPath);
  };

  // Sort files: directories first, then files, both alphabetically
  const sortedFiles = [...files].sort((a, b) => {
    if (a.isDirectory && !b.isDirectory) return -1;
    if (!a.isDirectory && b.isDirectory) return 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <Card className="border-border/60 shadow-sm">
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base font-medium">
            <FolderOpen className="h-4 w-4" />
            Container File Browser
            {containerName && (
              <span className="text-sm font-normal text-muted-foreground">
                ({containerName})
              </span>
            )}
          </CardTitle>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={loading}
              className="border-border/60"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Path Navigation */}
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleGoBack}
            disabled={currentPath === '/' || loading}
            className="border-border/60"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <div className="flex-1 px-3 py-2 bg-muted/50 rounded-md border border-border/60 text-sm font-mono truncate">
            {currentPath}
          </div>
        </div>

        {/* File List */}
        <div className="border border-border/60 rounded-md bg-muted/30 min-h-[300px] max-h-[500px] overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              <span className="ml-2 text-sm text-muted-foreground">Loading files...</span>
            </div>
          ) : sortedFiles.length === 0 ? (
            <div className="flex items-center justify-center py-12">
              <span className="text-sm text-muted-foreground">No files found</span>
            </div>
          ) : (
            <div className="divide-y divide-border/60">
              {sortedFiles.map((file) => (
                <div
                  key={file.path}
                  className="flex items-center justify-between p-3 hover:bg-muted/50 transition-colors cursor-pointer group"
                  onClick={() => file.isDirectory ? handleNavigate(file.path) : handleDownload(file)}
                >
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    {file.isDirectory ? (
                      <Folder className="h-5 w-5 text-blue-500 flex-shrink-0" />
                    ) : (
                      <File className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{file.name}</div>
                      {!file.isDirectory && (
                        <div className="text-xs text-muted-foreground">
                          {formatBytes(file.size)}
                        </div>
                      )}
                    </div>
                  </div>
                  {!file.isDirectory && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDownload(file);
                      }}
                      disabled={downloading === file.path}
                      className="opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      {downloading === file.path ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Download className="h-4 w-4" />
                      )}
                    </Button>
                  )}
                  {file.isDirectory && (
                    <ChevronRight className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Info */}
        <div className="text-xs text-muted-foreground">
          {files.length} {files.length === 1 ? 'item' : 'items'}
          {containerName && ` • Container: ${containerName}`}
        </div>
      </CardContent>
    </Card>
  );
}

