import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Loader2, CheckCircle2, XCircle, AlertCircle, RefreshCw } from 'lucide-react';
import type { AwsConfig } from '@/types/aws';
import { AWS_REGIONS } from '@/types/aws';

interface RepositoryStatus {
  exists: boolean;
  hasImages: boolean;
  imageCount: number;
  images: Array<{imageTag: string; imageDigest: string}>;
  repositoryUri?: string;
  message: string;
}

interface AwsConfigCardProps {
  config: AwsConfig;
  onConfigChange: (updates: Partial<AwsConfig>) => void;
  ecrRepositories?: string[];
  onConnectRepository?: (repository: string, region: string) => Promise<RepositoryStatus>;
  repositoryStatus?: RepositoryStatus | null;
  onClearRepositoryStatus?: () => void;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

export function AwsConfigCard({
  config,
  onConfigChange,
  ecrRepositories = ['cpu', 'gpu', 'hpc'],
  onConnectRepository,
  repositoryStatus,
  onClearRepositoryStatus,
  onRefresh,
  isRefreshing = false,
}: AwsConfigCardProps) {
  const [isCheckingRepo, setIsCheckingRepo] = useState(false);

  const handleConnectToRepository = async () => {
    if (!config.ecrRepository) {
      return;
    }
    
    if (!onConnectRepository) {
      return;
    }
    
    setIsCheckingRepo(true);
    try {
      await onConnectRepository(config.ecrRepository, config.region);
    } catch (error) {
      console.error('Failed to check repository:', error);
    } finally {
      setIsCheckingRepo(false);
    }
  };

  return (
    <Card className="border-border/60 shadow-sm">
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-medium">Repository Configuration</CardTitle>
          {onRefresh && (
            <Button
              variant="outline"
              size="sm"
              onClick={onRefresh}
              disabled={isRefreshing}
              className="gap-2 border-border/60"
            >
              <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
              {isRefreshing ? 'Refreshing...' : 'Refresh'}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4">
          <div className="grid grid-cols-[140px_1fr] items-center gap-3">
            <Label htmlFor="accountId" className="text-right text-sm text-muted-foreground">
              AWS Account ID
            </Label>
            <Input
              id="accountId"
              value={config.accountId}
              readOnly
              disabled
              placeholder="Auto-filled from login"
              className="bg-muted/50 border-border/60 cursor-not-allowed"
            />
          </div>

          <div className="grid grid-cols-[140px_1fr] items-center gap-3">
            <Label htmlFor="region" className="text-right text-sm text-muted-foreground">
              AWS Region
            </Label>
            <Select
              value={config.region}
              onValueChange={(value) => {
                onConfigChange({ region: value });
                // Clear repository status when region changes
                if (onClearRepositoryStatus) {
                  onClearRepositoryStatus();
                }
              }}
            >
              <SelectTrigger className="bg-muted/50 border-border/60">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {AWS_REGIONS.map((region) => (
                  <SelectItem key={region.value} value={region.value}>
                    {region.value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-[140px_1fr] items-center gap-3">
            <Label htmlFor="ecrRepo" className="text-right text-sm text-muted-foreground">
              ECR Repository
            </Label>
            <div className="flex gap-2 items-center">
              <Select
                value={config.ecrRepository}
                onValueChange={(value) => {
                  onConfigChange({ ecrRepository: value });
                  // Clear repository status when repository changes
                  if (onClearRepositoryStatus) {
                    onClearRepositoryStatus();
                  }
                }}
              >
                <SelectTrigger className="bg-muted/50 border-border/60 flex-1">
                  <SelectValue placeholder="Select repository" />
                </SelectTrigger>
                <SelectContent>
                  {ecrRepositories.map((repo) => (
                    <SelectItem key={repo} value={repo}>
                      {repo}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {onConnectRepository && (
                <Button
                  onClick={handleConnectToRepository}
                  disabled={!config.ecrRepository || isCheckingRepo}
                  size="sm"
                  variant="outline"
                  className="border-border/60"
                >
                  {isCheckingRepo ? (
                    <>
                      <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                      Checking...
                    </>
                  ) : (
                    'Connect'
                  )}
                </Button>
              )}
            </div>
          </div>

          {/* Repository Status Display */}
          {repositoryStatus && config.ecrRepository && (
            <div className={`p-3 rounded-md border ${
              !repositoryStatus.exists 
                ? 'bg-destructive/10 text-destructive border-destructive/20' 
                : !repositoryStatus.hasImages 
                  ? 'bg-yellow-500/10 text-yellow-600 border-yellow-500/20' 
                  : 'bg-green-500/10 text-green-600 border-green-500/20'
            }`}>
              <div className="flex items-start gap-2">
                {!repositoryStatus.exists ? (
                  <XCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                ) : !repositoryStatus.hasImages ? (
                  <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                ) : (
                  <CheckCircle2 className="h-4 w-4 mt-0.5 flex-shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{repositoryStatus.message}</p>
                  {repositoryStatus.hasImages && repositoryStatus.images.length > 0 && (
                    <div className="mt-2">
                      <p className="text-xs font-semibold mb-1">Available Images:</p>
                      <ul className="text-xs list-disc list-inside space-y-0.5">
                        {repositoryStatus.images.slice(0, 5).map((img, idx) => (
                          <li key={idx}>
                            Tag: <span className="font-mono">{img.imageTag}</span>
                          </li>
                        ))}
                        {repositoryStatus.images.length > 5 && (
                          <li className="text-muted-foreground">
                            ... and {repositoryStatus.images.length - 5} more
                          </li>
                        )}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
