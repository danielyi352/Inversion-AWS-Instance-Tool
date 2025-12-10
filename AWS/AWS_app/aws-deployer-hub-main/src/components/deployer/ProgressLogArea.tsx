import { useRef, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { Trash2 } from 'lucide-react';
import type { LogEntry } from '@/types/aws';

interface ProgressLogAreaProps {
  progress: number;
  logs: LogEntry[];
  onClearLogs: () => void;
}

export function ProgressLogArea({ progress, logs, onClearLogs }: ProgressLogAreaProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const getLogColor = (type: LogEntry['type']) => {
    switch (type) {
      case 'error':
        return 'text-destructive';
      case 'warning':
        return 'text-[hsl(var(--warning))]';
      case 'success':
        return 'text-[hsl(var(--success))]';
      default:
        return 'text-muted-foreground';
    }
  };

  return (
    <Card className="border-border/60 shadow-sm">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-medium">Progress & Logs</CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClearLogs}
            className="h-8 gap-1.5 text-muted-foreground hover:text-foreground"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Clear
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>Progress</span>
            <span>{progress}%</span>
          </div>
          <Progress value={progress} className="h-1.5" />
        </div>

        <ScrollArea className="h-48 rounded-lg border border-border/60 bg-muted/30">
          <div ref={scrollRef} className="p-3 font-mono text-xs space-y-1">
            {logs.length === 0 ? (
              <p className="text-muted-foreground">No logs yet...</p>
            ) : (
              logs.map((log, index) => (
                <div key={index} className="flex gap-2">
                  <span className="text-muted-foreground/60 shrink-0">
                    {new Date(log.timestamp).toLocaleTimeString()}
                  </span>
                  <span className={getLogColor(log.type)}>{log.message}</span>
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
