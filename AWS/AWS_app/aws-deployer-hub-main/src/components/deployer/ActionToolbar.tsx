import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { LogIn, RefreshCw, Rocket, Power, Terminal } from 'lucide-react';

interface ActionToolbarProps {
  isLoggedIn: boolean;
  hasSelectedInstance: boolean;
  onRoleLogin: () => void;
  onRefresh: () => void;
  onDeploy: () => void;
  onTerminate: () => void;
  onConnect: () => void;
}

export function ActionToolbar({
  isLoggedIn,
  hasSelectedInstance,
  onRoleLogin,
  onRefresh,
  onDeploy,
  onTerminate,
  onConnect,
}: ActionToolbarProps) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-3 py-2">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="outline"
            onClick={onRoleLogin}
            disabled={isLoggedIn}
            className="gap-2 border-border/60 bg-card hover:bg-muted"
          >
            <LogIn className="h-4 w-4" />
            Login with ARN
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>Login using your IAM Role ARN</p>
        </TooltipContent>
      </Tooltip>

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
            disabled={!isLoggedIn}
            className="gap-2"
          >
            <Rocket className="h-4 w-4" />
            Deploy
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>Launch a new EC2 instance using the selected ECR repository</p>
        </TooltipContent>
      </Tooltip>

      <div className="flex gap-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              onClick={onConnect}
              disabled={!hasSelectedInstance}
              className="gap-2 border-border/60 bg-card hover:bg-muted"
            >
              <Terminal className="h-4 w-4" />
              Connect
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>Open SSH connection to the selected instance</p>
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
    </div>
  );
}
