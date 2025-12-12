import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { AwsConfig } from '@/types/aws';
import { AWS_REGIONS, INSTANCE_TYPES } from '@/types/aws';

interface AwsConfigCardProps {
  config: AwsConfig;
  onConfigChange: (updates: Partial<AwsConfig>) => void;
  ecrRepositories?: string[];
  securityGroups?: string[];
}

export function AwsConfigCard({
  config,
  onConfigChange,
  ecrRepositories = ['cpu', 'gpu', 'hpc'],
  securityGroups = ['default', 'ssh-only', 'web-server'],
}: AwsConfigCardProps) {
  return (
    <Card className="border-border/60 shadow-sm">
      <CardHeader className="pb-4">
        <CardTitle className="text-base font-medium">AWS Configuration</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4">
          <div className="grid grid-cols-[140px_1fr] items-center gap-3">
            <Label htmlFor="region" className="text-right text-sm text-muted-foreground">
              AWS Region
            </Label>
            <Select
              value={config.region}
              onValueChange={(value) => onConfigChange({ region: value })}
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
            <Label htmlFor="accountId" className="text-right text-sm text-muted-foreground">
              AWS Account ID
            </Label>
            <Input
              id="accountId"
              value={config.accountId}
              onChange={(e) => onConfigChange({ accountId: e.target.value })}
              placeholder="095232028760"
              className="bg-muted/50 border-border/60"
            />
          </div>

          <div className="grid grid-cols-[140px_1fr] items-center gap-3">
            <Label htmlFor="ecrRepo" className="text-right text-sm text-muted-foreground">
              ECR Repository
            </Label>
            <Select
              value={config.ecrRepository}
              onValueChange={(value) => onConfigChange({ ecrRepository: value })}
            >
              <SelectTrigger className="bg-muted/50 border-border/60">
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
          </div>

          <div className="grid grid-cols-[140px_1fr] items-center gap-3">
            <Label htmlFor="instanceType" className="text-right text-sm text-muted-foreground">
              Instance Type
            </Label>
            <Select
              value={config.instanceType}
              onValueChange={(value) => onConfigChange({ instanceType: value })}
            >
              <SelectTrigger className="bg-muted/50 border-border/60">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {INSTANCE_TYPES.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    {type.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-[140px_1fr] items-center gap-3">
            <Label htmlFor="securityGroup" className="text-right text-sm text-muted-foreground">
              Security Group
            </Label>
            <Select
              value={config.securityGroup}
              onValueChange={(value) => onConfigChange({ securityGroup: value })}
            >
              <SelectTrigger className="bg-muted/50 border-border/60">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {securityGroups.map((sg) => (
                  <SelectItem key={sg} value={sg}>
                    {sg}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-[140px_1fr] items-center gap-3">
            <Label htmlFor="volumeSize" className="text-right text-sm text-muted-foreground">
              Volume Size (GiB)
            </Label>
            <Input
              id="volumeSize"
              type="number"
              min={1}
              max={2048}
              value={config.volumeSize}
              onChange={(e) => onConfigChange({ volumeSize: parseInt(e.target.value) || 30 })}
              className="bg-muted/50 border-border/60 w-32"
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
