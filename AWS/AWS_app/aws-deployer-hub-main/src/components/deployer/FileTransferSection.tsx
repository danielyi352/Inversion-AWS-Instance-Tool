import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Upload, Download, RefreshCw, FolderOpen } from 'lucide-react';
import { toast } from 'sonner';

interface FileTransferSectionProps {
  isConnected: boolean;
  onUpload?: (file: string, destination: string) => void;
  onDownload?: (remotePath: string, localPath: string) => void;
}

export function FileTransferSection({
  isConnected,
  onUpload,
  onDownload,
}: FileTransferSectionProps) {
  const [uploadFile, setUploadFile] = useState('');
  const [uploadDestination, setUploadDestination] = useState('/app');
  const [downloadContainer, setDownloadContainer] = useState('');
  const [remotePath, setRemotePath] = useState('');
  const [localDestination, setLocalDestination] = useState('');

  const containers = ['/app', '/workspace', '/data', '/home'];
  const availableContainers = ['Daniel-Inv', 'inversion-cpu-container'];

  const handleUpload = () => {
    if (!uploadFile) {
      toast.error('Please select a file to upload');
      return;
    }
    onUpload?.(uploadFile, uploadDestination);
    toast.success(`Uploading ${uploadFile} to ${uploadDestination}`);
  };

  const handleDownload = () => {
    if (!remotePath) {
      toast.error('Please specify a remote path');
      return;
    }
    onDownload?.(remotePath, localDestination);
    toast.success(`Downloading from ${remotePath}`);
  };

  const handleBrowseUpload = () => {
    setUploadFile('/Users/user/simulation.py');
  };

  const handleBrowseLocal = () => {
    setLocalDestination('/Users/user/Downloads');
  };

  return (
    <div className="grid gap-6 md:grid-cols-2">
      {/* Upload Card */}
      <Card className={`border-border/60 shadow-sm transition-opacity ${!isConnected ? 'opacity-50' : ''}`}>
        <CardHeader className="pb-4">
          <CardTitle className="flex items-center gap-2 text-base font-medium">
            <Upload className="h-4 w-4" />
            Upload to Container
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label className="text-sm text-muted-foreground">Source File</Label>
            <div className="flex gap-2">
              <Input
                placeholder="Drag file or click Browse..."
                value={uploadFile}
                onChange={(e) => setUploadFile(e.target.value)}
                disabled={!isConnected}
                className="bg-muted/50 border-border/60 flex-1"
              />
              <Button
                variant="outline"
                size="sm"
                onClick={handleBrowseUpload}
                disabled={!isConnected}
                className="border-border/60"
              >
                Browse
              </Button>
            </div>
          </div>

          <div className="space-y-2">
            <Label className="text-sm text-muted-foreground">Destination</Label>
            <div className="flex gap-2">
              <Select
                value={uploadDestination}
                onValueChange={setUploadDestination}
                disabled={!isConnected}
              >
                <SelectTrigger className="bg-muted/50 border-border/60 flex-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {containers.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button 
                variant="outline" 
                size="sm" 
                disabled={!isConnected}
                className="border-border/60"
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <Button
            className="w-full gap-2"
            onClick={handleUpload}
            disabled={!isConnected}
          >
            <Upload className="h-4 w-4" />
            Upload
          </Button>
        </CardContent>
      </Card>

      {/* Download Card */}
      <Card className={`border-border/60 shadow-sm transition-opacity ${!isConnected ? 'opacity-50' : ''}`}>
        <CardHeader className="pb-4">
          <CardTitle className="flex items-center gap-2 text-base font-medium">
            <Download className="h-4 w-4" />
            Download from Container
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label className="text-sm text-muted-foreground">Container</Label>
            <Select
              value={downloadContainer}
              onValueChange={setDownloadContainer}
              disabled={!isConnected}
            >
              <SelectTrigger className="bg-muted/50 border-border/60">
                <SelectValue placeholder="Select container" />
              </SelectTrigger>
              <SelectContent>
                {availableContainers.map((c) => (
                  <SelectItem key={c} value={c}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label className="text-sm text-muted-foreground">Remote Path</Label>
            <div className="flex gap-2">
              <Input
                placeholder="/..."
                value={remotePath}
                onChange={(e) => setRemotePath(e.target.value)}
                disabled={!isConnected}
                className="bg-muted/50 border-border/60 flex-1"
              />
              <Button 
                variant="outline" 
                size="sm" 
                disabled={!isConnected}
                className="border-border/60"
              >
                <FolderOpen className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div className="space-y-2">
            <Label className="text-sm text-muted-foreground">Local Destination</Label>
            <div className="flex gap-2">
              <Input
                placeholder="Drag or click Browse..."
                value={localDestination}
                onChange={(e) => setLocalDestination(e.target.value)}
                disabled={!isConnected}
                className="bg-muted/50 border-border/60 flex-1"
              />
              <Button
                variant="outline"
                size="sm"
                onClick={handleBrowseLocal}
                disabled={!isConnected}
                className="border-border/60"
              >
                Browse
              </Button>
            </div>
          </div>

          <Button
            className="w-full gap-2"
            variant="outline"
            onClick={handleDownload}
            disabled={!isConnected}
          >
            <Download className="h-4 w-4" />
            Download
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
