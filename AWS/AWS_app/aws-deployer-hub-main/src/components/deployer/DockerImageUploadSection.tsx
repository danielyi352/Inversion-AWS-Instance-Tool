import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Upload, Loader2, CheckCircle2, XCircle, AlertCircle, Terminal } from 'lucide-react';
import { toast } from 'sonner';
import { buildImageWithCodeBuild, getBuildStatus, clearRepository } from '@/lib/api';
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
  const [sourceCodeFile, setSourceCodeFile] = useState<File | null>(null);
  const [imageTag, setImageTag] = useState('latest');
  const [dockerfilePath, setDockerfilePath] = useState('Dockerfile');
  const [isBuilding, setIsBuilding] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [buildId, setBuildId] = useState<string | null>(null);
  const [buildStatus, setBuildStatus] = useState<{
    build_status: string;
    build_phase: string;
    build_complete: boolean;
    logs?: { deep_link?: string };
    error_info?: {
      failed_phase?: string;
      phase_context?: any[];
    };
  } | null>(null);

  // Poll build status if build is in progress
  useEffect(() => {
    if (!buildId || !isBuilding) return;

    let pollCount = 0;
    const maxPolls = 600; // 30 minutes max (600 * 3 seconds)

    const pollInterval = setInterval(async () => {
      pollCount++;
      
      if (pollCount > maxPolls) {
        clearInterval(pollInterval);
        setIsBuilding(false);
        toast.error('Build status polling timed out. Check AWS CodeBuild console for status.');
        return;
      }

      try {
        const status = await getBuildStatus(buildId, config.region);
        console.log('Build status update:', status);
        setBuildStatus(status);

        if (status.build_complete) {
          setIsBuilding(false);
          clearInterval(pollInterval);
          
          if (status.build_status === 'SUCCEEDED') {
            toast.success('Docker image built and pushed successfully!');
            if (onRepositoryStatusChange) {
              // Wait a moment for ECR to update, then refresh
              setTimeout(() => {
                onRepositoryStatusChange();
              }, 2000);
            }
          } else if (status.build_status === 'FAILED') {
            const errorMsg = status.logs?.deep_link 
              ? `Build failed in phase: ${status.build_phase}. Click "View Build Logs" for details.`
              : `Build failed in phase: ${status.build_phase}. Check AWS CodeBuild console for details.`;
            toast.error(errorMsg, { duration: 10000 });
          } else {
            toast.warning(`Build completed with status: ${status.build_status}`);
          }
        }
      } catch (error) {
        console.error('Failed to get build status:', error);
        const errorMessage = error instanceof Error ? error.message : String(error);
        if (errorMessage.includes('404') || errorMessage.includes('not found')) {
          clearInterval(pollInterval);
          setIsBuilding(false);
          toast.error('Build not found. It may have been deleted or the build ID is invalid.');
        }
      }
    }, 3000); // Poll every 3 seconds

    return () => clearInterval(pollInterval);
  }, [buildId, isBuilding, config.region, onRepositoryStatusChange]);

  const handleBuildImage = async () => {
    if (!config.ecrRepository) {
      toast.error('Please select a repository first');
      return;
    }

    if (!sourceCodeFile) {
      toast.error('Please select a source code zip file');
      return;
    }

    setIsBuilding(true);
    setBuildStatus(null);
    setBuildId(null);
    
    try {
      console.log('Starting build with:', {
        repository: config.ecrRepository,
        imageTag,
        region: config.region,
        dockerfilePath,
        fileName: sourceCodeFile.name,
        fileSize: sourceCodeFile.size
      });
      
      const result = await buildImageWithCodeBuild(
        config.ecrRepository,
        sourceCodeFile,
        imageTag,
        config.region,
        dockerfilePath
      );
      
      console.log('Build started successfully:', result);
      setBuildId(result.build_id);
      const buildIdShort = result.build_id.split('/').pop() || result.build_id;
      toast.success(`Build started! Build ID: ${buildIdShort}`, { duration: 5000 });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      console.error('Build start error:', error);
      console.error('Error message:', errorMessage);
      
      // Parse error details if available
      let displayMessage = errorMessage;
      try {
        // Try to extract detail from JSON error response
        if (errorMessage.includes('detail')) {
          const match = errorMessage.match(/detail["\']?\s*:\s*["\']?([^"\'}]+)/i);
          if (match) {
            displayMessage = match[1];
          }
        }
        // Try full JSON parse
        const errorJson = JSON.parse(errorMessage);
        if (errorJson.detail) {
          displayMessage = errorJson.detail;
        } else if (errorJson.message) {
          displayMessage = errorJson.message;
        }
      } catch {
        // Not JSON, use as-is but try to clean it up
        if (errorMessage.length > 200) {
          displayMessage = errorMessage.substring(0, 200) + '...';
        }
      }
      
      toast.error(`Failed to start build: ${displayMessage}`, { duration: 10000 });
      setIsBuilding(false);
      setBuildStatus(null);
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

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'SUCCEEDED': return 'text-green-600';
      case 'FAILED': return 'text-red-600';
      case 'IN_PROGRESS': return 'text-blue-600';
      default: return 'text-yellow-600';
    }
  };

  if (!config.ecrRepository) {
    return (
      <Card className="border-border/60 shadow-sm">
        <CardHeader className="pb-4">
          <CardTitle className="flex items-center gap-2 text-base font-medium">
            <Terminal className="h-4 w-4" />
            Build & Push Docker Image
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center">
            Please select a repository first
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-border/60 shadow-sm">
      <CardHeader className="pb-4">
        <CardTitle className="flex items-center gap-2 text-base font-medium">
          <Terminal className="h-4 w-4" />
          Build & Push Docker Image
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Info Alert */}
        <Alert className="bg-blue-500/10 border-blue-500/20">
          <AlertCircle className="h-4 w-4 text-blue-600" />
          <AlertDescription className="text-sm">
            Upload your source code as a zip file. AWS CodeBuild will build your Docker image and push it to ECR automatically.
          </AlertDescription>
        </Alert>

        {/* Source Code Upload */}
        <div className="space-y-2">
          <Label htmlFor="sourceCode" className="text-sm">
            Source Code (ZIP file) *
          </Label>
          <Input
            id="sourceCode"
            type="file"
            accept=".zip,.tar,.tar.gz"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) {
                setSourceCodeFile(file);
              }
            }}
            disabled={isBuilding}
            className="bg-muted/50 border-border/60"
          />
          {sourceCodeFile && (
            <p className="text-xs text-muted-foreground">
              Selected: {sourceCodeFile.name} ({(sourceCodeFile.size / 1024 / 1024).toFixed(2)} MB)
              {sourceCodeFile.name.endsWith('.tar') || sourceCodeFile.name.endsWith('.tar.gz') ? (
                <span className="block mt-1 text-blue-600">Docker image tar file - will be loaded and pushed</span>
              ) : (
                <span className="block mt-1 text-blue-600">Source code zip - will be built from Dockerfile</span>
              )}
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Upload either: (1) Source code zip file with Dockerfile, or (2) Docker image tar file (from docker save)
          </p>
        </div>

        {/* Dockerfile Path */}
        <div className="space-y-2">
          <Label htmlFor="dockerfilePath" className="text-sm">
            Dockerfile Path
          </Label>
          <Input
            id="dockerfilePath"
            placeholder="Dockerfile"
            value={dockerfilePath}
            onChange={(e) => setDockerfilePath(e.target.value)}
            disabled={isBuilding}
            className="bg-muted/50 border-border/60"
          />
          <p className="text-xs text-muted-foreground">
            Path to Dockerfile within your source code (default: Dockerfile)
          </p>
        </div>

        {/* Image Tag */}
        <div className="space-y-2">
          <Label htmlFor="imageTag" className="text-sm">
            Image Tag
          </Label>
          <Input
            id="imageTag"
            placeholder="latest"
            value={imageTag}
            onChange={(e) => setImageTag(e.target.value)}
            disabled={isBuilding}
            className="bg-muted/50 border-border/60"
          />
          <p className="text-xs text-muted-foreground">
            Tag to use for the Docker image (default: latest)
          </p>
        </div>

        {/* Build Status */}
        {buildStatus && (
          <Alert className={buildStatus.build_status === 'SUCCEEDED' ? 'bg-green-500/10 border-green-500/20' : buildStatus.build_status === 'FAILED' ? 'bg-red-500/10 border-red-500/20' : 'bg-blue-500/10 border-blue-500/20'}>
            <div className="flex items-start gap-2">
              {buildStatus.build_status === 'SUCCEEDED' ? (
                <CheckCircle2 className="h-4 w-4 text-green-600 mt-0.5" />
              ) : buildStatus.build_status === 'FAILED' ? (
                <XCircle className="h-4 w-4 text-red-600 mt-0.5" />
              ) : (
                <Loader2 className="h-4 w-4 text-blue-600 mt-0.5 animate-spin" />
              )}
              <div className="flex-1">
                <AlertDescription className="text-sm">
                  <div className="font-semibold mb-1">
                    Status: <span className={getStatusColor(buildStatus.build_status)}>{buildStatus.build_status}</span>
                  </div>
                  {buildStatus.build_phase && (
                    <div className="text-xs text-muted-foreground">
                      Phase: {buildStatus.build_phase}
                    </div>
                  )}
                  {buildStatus.error_info?.failed_phase && (
                    <div className="text-xs text-red-600 mt-1">
                      Failed in phase: {buildStatus.error_info.failed_phase}
                    </div>
                  )}
                  {buildStatus.logs?.deep_link && (
                    <a
                      href={buildStatus.logs.deep_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-blue-600 hover:underline mt-1 block"
                    >
                      View Build Logs →
                    </a>
                  )}
                </AlertDescription>
              </div>
            </div>
          </Alert>
        )}

        {/* Repository Info */}
        {config.ecrRepository && config.accountId && (
          <div className="p-3 rounded-md bg-muted/50 border border-border/60">
            <p className="text-xs font-semibold text-muted-foreground mb-1">Target Repository:</p>
            <p className="text-sm font-mono break-all">
              {config.accountId}.dkr.ecr.{config.region}.amazonaws.com/{config.ecrRepository}:{imageTag}
            </p>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex gap-2">
          <Button
            className="flex-1 gap-2"
            onClick={handleBuildImage}
            disabled={!sourceCodeFile || isBuilding || isClearing}
          >
            {isBuilding ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Building...
              </>
            ) : (
              <>
                <Upload className="h-4 w-4" />
                Build & Push
              </>
            )}
          </Button>
          
          {repositoryStatus?.hasImages && (
            <Button
              variant="destructive"
              onClick={handleClearRepository}
              disabled={isClearing || isBuilding}
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
      </CardContent>
    </Card>
  );
}
