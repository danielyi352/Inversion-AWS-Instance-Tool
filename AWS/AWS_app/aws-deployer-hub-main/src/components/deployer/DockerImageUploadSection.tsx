import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Upload, Loader2, CheckCircle2, XCircle, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';
import { checkDockerAvailability, pushImageToEcr, clearRepository } from '@/lib/api';
import type { AwsConfig } from '@/types/aws';

interface DockerImageUploadSectionProps {
  config: AwsConfig;
  repositoryStatus?: {
    exists: boolean;
    hasImages: boolean;
    imageCount: number;
    images: Array<{imageTag: string; imageDigest: string}>;
    repositoryUri?: string;
    message: string;
  } | null;
  onRepositoryStatusChange?: () => void;
}

export function DockerImageUploadSection({
  config,
  repositoryStatus,
  onRepositoryStatusChange,
}: DockerImageUploadSectionProps) {
  const [tarFile, setTarFile] = useState<File | null>(null);
  const [imageTag, setImageTag] = useState('latest');
  const [isPushing, setIsPushing] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [dockerStatus, setDockerStatus] = useState<{
    available: boolean;
    version: string | null;
    daemon_running: boolean;
    message: string;
  } | null>(null);
  const [isCheckingDocker, setIsCheckingDocker] = useState(false);

  // Check Docker availability on mount
  useEffect(() => {
    checkDocker();
  }, []);

  const checkDocker = async () => {
    setIsCheckingDocker(true);
    try {
      const status = await checkDockerAvailability();
      setDockerStatus(status);
      if (!status.available) {
        toast.error(`Docker is not available: ${status.message}`);
      } else if (!status.daemon_running) {
        toast.warning('Docker is installed but daemon is not running');
      }
    } catch (error) {
      toast.error(`Failed to check Docker: ${error}`);
      setDockerStatus({
        available: false,
        version: null,
        daemon_running: false,
        message: 'Failed to check Docker status',
      });
    } finally {
      setIsCheckingDocker(false);
    }
  };

  const handlePushImage = async () => {
    if (!config.ecrRepository) {
      toast.error('Please select a repository first');
      return;
    }

    if (!tarFile) {
      toast.error('Please select a Docker image tar file');
      return;
    }

    if (!dockerStatus?.available || !dockerStatus?.daemon_running) {
      toast.error('Docker is not available. Please ensure Docker is installed and running.');
      return;
    }

    setIsPushing(true);
    try {
      const result = await pushImageToEcr(
        config.ecrRepository,
        tarFile,
        imageTag,
        config.region
      );
      toast.success(result.message);
      // Refresh repository status after successful push
      if (onRepositoryStatusChange) {
        onRepositoryStatusChange();
      }
      // Clear the file input
      setTarFile(null);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(`Failed to push image: ${errorMessage}`);
    } finally {
      setIsPushing(false);
    }
  };

  const handleClearRepository = async () => {
    if (!config.ecrRepository) {
      toast.error('Please select a repository first');
      return;
    }

    if (!repositoryStatus?.hasImages) {
      toast.info('Repository is already empty');
      return;
    }

    if (!confirm(`Are you sure you want to delete all images from repository '${config.ecrRepository}'? This action cannot be undone.`)) {
      return;
    }

    setIsClearing(true);
    try {
      const result = await clearRepository(config.ecrRepository, config.region);
      toast.success(result.message);
      // Refresh repository status after clearing
      if (onRepositoryStatusChange) {
        onRepositoryStatusChange();
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(`Failed to clear repository: ${errorMessage}`);
    } finally {
      setIsClearing(false);
    }
  };

  const isDisabled = !config.ecrRepository || !dockerStatus?.available || !dockerStatus?.daemon_running || isPushing || !tarFile;

  return (
    <Card className="border-border/60 shadow-sm">
      <CardHeader className="pb-4">
        <CardTitle className="flex items-center gap-2 text-base font-medium">
          <Upload className="h-4 w-4" />
          Push Docker Image to ECR
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Docker Status */}
        {dockerStatus && (
          <Alert className={dockerStatus.available && dockerStatus.daemon_running ? 'bg-green-500/10 border-green-500/20' : 'bg-yellow-500/10 border-yellow-500/20'}>
            <div className="flex items-start gap-2">
              {dockerStatus.available && dockerStatus.daemon_running ? (
                <CheckCircle2 className="h-4 w-4 text-green-600 mt-0.5" />
              ) : (
                <AlertCircle className="h-4 w-4 text-yellow-600 mt-0.5" />
              )}
              <div className="flex-1">
                <AlertDescription className="text-sm">
                  {dockerStatus.message}
                  {dockerStatus.version && (
                    <span className="block text-xs text-muted-foreground mt-1">
                      {dockerStatus.version}
                    </span>
                  )}
                </AlertDescription>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={checkDocker}
                disabled={isCheckingDocker}
                className="h-6 w-6 p-0"
              >
                {isCheckingDocker ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <span className="text-xs">↻</span>
                )}
              </Button>
            </div>
          </Alert>
        )}

        {/* Repository Status Warning */}
        {repositoryStatus && !repositoryStatus.exists && (
          <Alert className="bg-yellow-500/10 border-yellow-500/20">
            <AlertCircle className="h-4 w-4 text-yellow-600" />
            <AlertDescription className="text-sm">
              Repository will be created automatically when you push the image.
            </AlertDescription>
          </Alert>
        )}

        {/* Tar File Input */}
        <div className="space-y-2">
          <Label htmlFor="tarFile" className="text-sm text-muted-foreground">
            Docker Image Tar File
          </Label>
          <Input
            id="tarFile"
            type="file"
            accept=".tar"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) {
                setTarFile(file);
              }
            }}
            disabled={isPushing}
            className="bg-muted/50 border-border/60"
          />
          {tarFile && (
            <p className="text-xs text-muted-foreground">
              Selected: {tarFile.name} ({(tarFile.size / 1024 / 1024).toFixed(2)} MB)
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Select a tar file created with: <code className="text-xs">docker save myimage:latest -o myimage.tar</code>
          </p>
        </div>

        {/* Image Tag Input */}
        <div className="space-y-2">
          <Label htmlFor="imageTag" className="text-sm text-muted-foreground">
            ECR Image Tag
          </Label>
          <Input
            id="imageTag"
            placeholder="latest"
            value={imageTag}
            onChange={(e) => setImageTag(e.target.value)}
            disabled={isDisabled}
            className="bg-muted/50 border-border/60"
          />
          <p className="text-xs text-muted-foreground">
            Tag to use when pushing to ECR (default: latest)
          </p>
        </div>

        {/* Repository Info */}
        {config.ecrRepository && (
          <div className="p-3 rounded-md bg-muted/50 border border-border/60">
            <p className="text-xs font-semibold text-muted-foreground mb-1">Target Repository:</p>
            <p className="text-sm font-mono">
              {config.accountId}.dkr.ecr.{config.region}.amazonaws.com/{config.ecrRepository}:{imageTag}
            </p>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex gap-2">
          <Button
            className="flex-1 gap-2"
            onClick={handlePushImage}
            disabled={isDisabled}
          >
            {isPushing ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Pushing...
              </>
            ) : (
              <>
                <Upload className="h-4 w-4" />
                Push to ECR
              </>
            )}
          </Button>
          
          {repositoryStatus?.hasImages && (
            <Button
              variant="destructive"
              onClick={handleClearRepository}
              disabled={isClearing || isPushing}
              className="gap-2"
            >
              {isClearing ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Clearing...
                </>
              ) : (
                <>
                  <XCircle className="h-4 w-4" />
                  Clear
                </>
              )}
            </Button>
          )}
        </div>

        {!config.ecrRepository && (
          <p className="text-xs text-muted-foreground text-center">
            Please select a repository first
          </p>
        )}
      </CardContent>
    </Card>
  );
}

