import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Server, Rocket, ChevronDown, Settings } from 'lucide-react';
import { useState } from 'react';
import type { AwsConfig } from '@/types/aws';
import { INSTANCE_TYPES } from '@/types/aws';

const VOLUME_TYPES = [
  { value: 'gp3', label: 'gp3 - General Purpose SSD (Recommended)' },
  { value: 'gp2', label: 'gp2 - General Purpose SSD' },
  { value: 'io1', label: 'io1 - Provisioned IOPS SSD' },
  { value: 'io2', label: 'io2 - Provisioned IOPS SSD (Latest)' },
  { value: 'st1', label: 'st1 - Throughput Optimized HDD' },
  { value: 'sc1', label: 'sc1 - Cold HDD' },
] as const;

const AMI_TYPES = [
  { value: 'auto', label: 'Auto-detect (based on repository name)' },
  { value: 'al2023', label: 'Amazon Linux 2023 (CPU)' },
  { value: 'deep-learning-gpu', label: 'Deep Learning Base GPU AMI (GPU)' },
  { value: 'ubuntu-22', label: 'Ubuntu Server 22.04 LTS' },
  { value: 'custom', label: 'Custom AMI ID' },
] as const;

interface InstanceConfigCardProps {
  config: AwsConfig;
  onConfigChange: (updates: Partial<AwsConfig>) => void;
  isLoggedIn?: boolean;
  repositoryHasImages?: boolean;
  onDeploy?: () => void;
}

export function InstanceConfigCard({
  config,
  onConfigChange,
  isLoggedIn = false,
  repositoryHasImages = false,
  onDeploy,
}: InstanceConfigCardProps) {
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);

  return (
    <Card className="border-border/60 shadow-sm">
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base font-medium">
            <Server className="h-4 w-4" />
            Instance Configuration
          </CardTitle>
          {onDeploy && (
            <Button
              onClick={onDeploy}
              disabled={!isLoggedIn || !repositoryHasImages}
              className="gap-2"
            >
              <Rocket className="h-4 w-4" />
              Deploy
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <Collapsible open={isAdvancedOpen} onOpenChange={setIsAdvancedOpen}>
          <CollapsibleTrigger asChild>
            <Button
              variant="ghost"
              className="w-full justify-between mb-4"
            >
              <span className="flex items-center gap-2">
                <Settings className="h-4 w-4" />
                Advanced Settings
              </span>
              <ChevronDown
                className={`h-4 w-4 transition-transform duration-200 ${
                  isAdvancedOpen ? 'transform rotate-180' : ''
                }`}
              />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="grid gap-4 pt-2">
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
                <Label htmlFor="amiType" className="text-right text-sm text-muted-foreground">
                  OS Image (AMI)
                </Label>
                <div className="space-y-2">
                  <Select
                    value={config.amiType || 'auto'}
                    onValueChange={(value) => {
                      if (value === 'custom') {
                        onConfigChange({ amiType: 'custom', amiId: '' });
                      } else {
                        onConfigChange({ amiType: value, amiId: undefined });
                      }
                    }}
                  >
                    <SelectTrigger className="bg-muted/50 border-border/60">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {AMI_TYPES.map((type) => (
                        <SelectItem key={type.value} value={type.value}>
                          {type.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {config.amiType === 'custom' && (
                    <Input
                      id="amiId"
                      placeholder="ami-xxxxxxxxxxxxxxxxx"
                      value={config.amiId || ''}
                      onChange={(e) => onConfigChange({ amiId: e.target.value || undefined })}
                      className="bg-muted/50 border-border/60 font-mono text-xs"
                    />
                  )}
                </div>
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

              <div className="grid grid-cols-[140px_1fr] items-center gap-3">
                <Label htmlFor="volumeType" className="text-right text-sm text-muted-foreground">
                  Volume Type
                </Label>
                <Select
                  value={config.volumeType || 'gp3'}
                  onValueChange={(value) => onConfigChange({ volumeType: value })}
                >
                  <SelectTrigger className="bg-muted/50 border-border/60">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {VOLUME_TYPES.map((type) => (
                      <SelectItem key={type.value} value={type.value}>
                        {type.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  );
}

