import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { LogOut } from 'lucide-react';
import { useAwsConfig } from '@/hooks/useAwsConfig';
import { AwsConfigCard } from './AwsConfigCard';
import { InstanceConfigCard } from './InstanceConfigCard';
import { StatusCard } from './StatusCard';
import { ProgressLogArea } from './ProgressLogArea';
import { DockerImageUploadSection } from './DockerImageUploadSection';
import { ContainerFileBrowser } from './ContainerFileBrowser';
import { ContainerLogsViewer } from './ContainerLogsViewer';
import { AwsConnectionDialog } from './AwsConnectionDialog';
import { LogoutDialog } from './LogoutDialog';

export function InversionDeployer() {
  const navigate = useNavigate();
  const [loginDialogOpen, setLoginDialogOpen] = useState(false);
  const [logoutDialogOpen, setLogoutDialogOpen] = useState(false);
  const [hasNoOrg, setHasNoOrg] = useState(false);
  
  const {
    config,
    updateConfig,
    rememberSettings,
    setRememberSettings,
    isLoggedIn,
    instances,
    selectedInstance,
    setSelectedInstance,
    logs,
    clearLogs,
    progress,
    metadata,
    repositoryStatus,
    clearRepositoryStatus,
    isRefreshing,
    handleRoleLogin,
    handleRefresh,
    handleConnectRepository,
    handleDeploy,
    handleTerminate,
    handleConnect,
    handleLogout,
  } = useAwsConfig();

  // Note: Authentication is now handled at the route level in Dashboard component

  return (
    <div className="min-h-screen bg-background">
      {/* Palantir-style top bar */}
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <button
            onClick={() => navigate('/dashboard')}
            className="flex items-center gap-3 hover:opacity-80 transition-opacity cursor-pointer"
          >
            <svg className="h-7 w-7" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2L2 7L12 12L22 7L12 2Z" className="fill-foreground" />
              <path d="M2 17L12 22L22 17" className="stroke-foreground" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M2 12L12 17L22 12" className="stroke-foreground" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-lg font-medium tracking-tight">Inversion Deployer</span>
          </button>
          <div className="flex items-center gap-4">
            <Button
              variant="outline"
              onClick={() => setLogoutDialogOpen(true)}
              className="gap-2"
            >
              <LogOut className="h-4 w-4" />
              Logout
            </Button>
            <p className="text-sm text-muted-foreground hidden md:block">
              AWS EC2 Deployment & Container Management
            </p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        {!isLoggedIn ? (
          // Show AWS connection prompt when user is logged in but AWS is not connected
          <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-6">
            <div className="text-center space-y-4">
              <h2 className="text-2xl font-semibold">Connect to AWS</h2>
              <p className="text-muted-foreground">
                Please connect your AWS account to get started
              </p>
            </div>
            <Button
              onClick={() => setLoginDialogOpen(true)}
              size="lg"
              className="gap-2"
            >
              Connect AWS Account
            </Button>
          </div>
        ) : (
          // Show main content when logged in
          <div className="space-y-8">
            {/* Top Panels */}
            <div className="grid gap-6 lg:grid-cols-2">
              <AwsConfigCard
                config={config}
                onConfigChange={updateConfig}
                ecrRepositories={metadata.repositories}
                onConnectRepository={handleConnectRepository}
                repositoryStatus={repositoryStatus}
                onClearRepositoryStatus={clearRepositoryStatus}
                onRefresh={handleRefresh}
                isRefreshing={isRefreshing}
              />
              <StatusCard
                isLoggedIn={isLoggedIn}
                instances={instances}
                selectedInstance={selectedInstance}
                onSelectInstance={setSelectedInstance}
                onTerminate={handleTerminate}
              />
            </div>

            {/* Remember Settings */}
            <div className="flex items-center gap-2">
              <Checkbox
                id="remember"
                checked={rememberSettings}
                onCheckedChange={(checked) => setRememberSettings(checked as boolean)}
                className="border-muted-foreground/40 data-[state=checked]:bg-foreground data-[state=checked]:border-foreground"
              />
              <Label htmlFor="remember" className="text-sm text-muted-foreground cursor-pointer">
                Remember settings
              </Label>
            </div>

            {/* Docker Image Upload - Show when repository is connected (even if empty) */}
            {repositoryStatus?.exists && config.ecrRepository && (
              <DockerImageUploadSection
                config={config}
                repositoryStatus={repositoryStatus}
                onRepositoryStatusChange={() => {
                  if (config.ecrRepository) {
                    handleConnectRepository(config.ecrRepository, config.region);
                  }
                }}
              />
            )}

            {/* Instance Configuration - Show when repository has images (ready to deploy) */}
            {repositoryStatus?.hasImages && config.ecrRepository && (
              <InstanceConfigCard
                config={config}
                onConfigChange={updateConfig}
                isLoggedIn={isLoggedIn}
                repositoryHasImages={repositoryStatus?.hasImages ?? false}
                onDeploy={handleDeploy}
              />
            )}

            {/* Container File Browser */}
            {selectedInstance && (
              <ContainerFileBrowser
                instanceId={selectedInstance}
                region={config.region}
                accountId={config.accountId}
                repository={config.ecrRepository}
              />
            )}

            {/* Container Logs Viewer */}
            {selectedInstance && (
              <ContainerLogsViewer
                instanceId={selectedInstance}
                region={config.region}
                accountId={config.accountId}
                repository={config.ecrRepository}
              />
            )}

            {/* Progress & Logs - Moved to bottom */}
            <ProgressLogArea progress={progress} logs={logs} onClearLogs={clearLogs} />

            {/* Footer */}
            <footer className="flex items-center justify-center gap-4 border-t border-border pt-6 text-sm text-muted-foreground">
              <span>
                {selectedInstance
                  ? `Selected: ${instances.find((i) => i.id === selectedInstance)?.name || selectedInstance}`
                  : 'No instance selected'}
              </span>
              {selectedInstance && (
                <>
                  <span className="text-border">•</span>
                  <span className="font-mono text-xs">
                    {instances.find((i) => i.id === selectedInstance)?.publicDns || '-'}
                  </span>
                </>
              )}
            </footer>
          </div>
        )}

        {/* AWS Connection Dialog */}
        <AwsConnectionDialog
          open={loginDialogOpen}
          required={!isLoggedIn}
          onOpenChange={(open) => {
            // Allow closing if already logged in OR if user has no organization
            if (isLoggedIn || hasNoOrg) {
              setLoginDialogOpen(open);
            }
          }}
          onHasNoOrg={setHasNoOrg}
          onRoleArnReceived={async (roleArn, accountId, externalId, region) => {
            await handleRoleLogin(roleArn, accountId, externalId, region);
            setLoginDialogOpen(false);
          }}
        />

        {/* Logout Dialog */}
        <LogoutDialog
          open={logoutDialogOpen}
          onOpenChange={setLogoutDialogOpen}
          onConfirm={handleLogout}
        />
      </main>
    </div>
  );
}
