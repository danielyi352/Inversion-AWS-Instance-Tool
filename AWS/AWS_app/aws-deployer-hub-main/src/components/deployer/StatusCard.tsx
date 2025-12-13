import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Power } from 'lucide-react';
import type { RunningInstance } from '@/types/aws';

interface StatusCardProps {
  isLoggedIn: boolean;
  instances: RunningInstance[];
  selectedInstance: string | null;
  onSelectInstance: (id: string) => void;
  onTerminate?: () => void;
}

export function StatusCard({
  isLoggedIn,
  instances,
  selectedInstance,
  onSelectInstance,
  onTerminate,
}: StatusCardProps) {
  const selectedInstanceData = instances.find((i) => i.id === selectedInstance);

  return (
    <Card className="border-border/60 shadow-sm">
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-medium">Status & Instances</CardTitle>
          {onTerminate && (
            <Button
              variant="outline"
              onClick={onTerminate}
              disabled={!selectedInstance}
              className="gap-2 border-destructive/60 text-destructive hover:bg-destructive hover:text-destructive-foreground"
            >
              <Power className="h-4 w-4" />
              Terminate
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex items-center gap-3">
          <Label className="text-sm text-muted-foreground">AWS SSO Status</Label>
          <div className="flex items-center gap-2">
            <div
              className={`h-2.5 w-2.5 rounded-full ${
                isLoggedIn ? 'bg-[hsl(var(--success))]' : 'bg-destructive'
              }`}
            />
            <span className="text-sm font-medium">{isLoggedIn ? 'Connected' : 'Not connected'}</span>
          </div>
        </div>

        <div className="space-y-2">
          <Label className="text-sm text-muted-foreground">Running Instances</Label>
          <Select
            value={selectedInstance || ''}
            onValueChange={onSelectInstance}
            disabled={instances.length === 0}
          >
            <SelectTrigger className="bg-muted/50 border-border/60">
              <SelectValue placeholder={instances.length ? 'Select instance' : 'No instances available'} />
            </SelectTrigger>
            <SelectContent>
              {instances.map((instance) => (
                <SelectItem key={instance.id} value={instance.id}>
                  {instance.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {selectedInstanceData && (
          <div className="space-y-2.5 rounded-lg border border-border/60 bg-muted/30 p-4 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Instance ID</span>
              <span className="font-mono text-xs">{selectedInstanceData.id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Type</span>
              <span>{selectedInstanceData.instanceType}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Status</span>
              <span className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 rounded-full ${
                    selectedInstanceData.status === 'running'
                      ? 'bg-[hsl(var(--success))]'
                      : 'bg-[hsl(var(--warning))]'
                  }`}
                />
                {selectedInstanceData.status}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Public DNS</span>
              <span className="font-mono text-xs max-w-[180px] truncate">
                {selectedInstanceData.publicDns}
              </span>
            </div>
          </div>
        )}

        <div className="grid grid-cols-3 gap-3 pt-2">
          <div className="rounded-lg border border-border/60 bg-muted/30 p-3 text-center">
            <div className="text-2xl font-semibold">{instances.length}</div>
            <div className="text-xs text-muted-foreground mt-0.5">Total</div>
          </div>
          <div className="rounded-lg border border-border/60 bg-muted/30 p-3 text-center">
            <div className="text-2xl font-semibold text-[hsl(var(--success))]">
              {instances.filter((i) => i.status === 'running').length}
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">Running</div>
          </div>
          <div className="rounded-lg border border-border/60 bg-muted/30 p-3 text-center">
            <div className="text-lg font-semibold truncate">
              {selectedInstanceData?.instanceType.split('.')[0] || '—'}
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">Type</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
