import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { RefreshCw, Rocket, Power } from 'lucide-react';

interface ActionToolbarProps {
  isLoggedIn: boolean;
  hasSelectedInstance: boolean;
  repositoryHasImages?: boolean;
  onRefresh: () => void;
  onDeploy: () => void;
  onTerminate: () => void;
}

export function ActionToolbar({
  isLoggedIn,
  hasSelectedInstance,
  repositoryHasImages = false,
  onRefresh,
  onDeploy,
  onTerminate,
}: ActionToolbarProps) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-3 py-2">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button 
            variant="outline" 
            onClick={onRefresh} 
            className="gap-2 border-border/60 bg-card hover:bg-muted"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>Reload profiles, repositories, and running instances</p>
        </TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            onClick={onDeploy}
            disabled={!isLoggedIn || !repositoryHasImages}
            className="gap-2"
          >
            <Rocket className="h-4 w-4" />
            Deploy
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>
            {!repositoryHasImages 
              ? "Repository is empty. Please connect to a repository with images first."
              : "Launch a new EC2 instance using the selected ECR repository"}
          </p>
        </TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="outline"
            onClick={onTerminate}
            disabled={!hasSelectedInstance}
            className="gap-2 border-destructive/60 text-destructive hover:bg-destructive hover:text-destructive-foreground"
          >
            <Power className="h-4 w-4" />
            Terminate
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>Stop and terminate the selected EC2 instance</p>
        </TooltipContent>
      </Tooltip>
    </div>
  );
}
