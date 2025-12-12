import { useState, useEffect } from 'react';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { LogOut } from 'lucide-react';
import { useAwsConfig } from '@/hooks/useAwsConfig';
import { AwsConfigCard } from './AwsConfigCard';
import { StatusCard } from './StatusCard';
import { ActionToolbar } from './ActionToolbar';
import { ProgressLogArea } from './ProgressLogArea';
import { FileTransferSection } from './FileTransferSection';
import { RoleLoginDialog } from './RoleLoginDialog';
import { LogoutDialog } from './LogoutDialog';

export function InversionDeployer() {
  const [loginDialogOpen, setLoginDialogOpen] = useState(false);
  const [logoutDialogOpen, setLogoutDialogOpen] = useState(false);
  
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
    handleRoleLogin,
    handleRefresh,
    handleConnectRepository,
    handleDeploy,
    handleTerminate,
    handleConnect,
    handleUpload,
    handleDownload,
    handleLogout,
  } = useAwsConfig();

  // Auto-open login dialog if not logged in
  useEffect(() => {
    if (!isLoggedIn) {
      setLoginDialogOpen(true);
    }
  }, [isLoggedIn]);

  return (
    <div className="min-h-screen bg-background">
      {/* Palantir-style top bar */}
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <svg className="h-7 w-7" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2L2 7L12 12L22 7L12 2Z" className="fill-foreground" />
              <path d="M2 17L12 22L22 17" className="stroke-foreground" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M2 12L12 17L22 12" className="stroke-foreground" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-lg font-medium tracking-tight">Inversion Deployer</span>
          </div>
          <div className="flex items-center gap-4">
            {isLoggedIn && (
              <Button
                variant="outline"
                onClick={() => setLogoutDialogOpen(true)}
                className="gap-2"
              >
                <LogOut className="h-4 w-4" />
                Logout
              </Button>
            )}
            <p className="text-sm text-muted-foreground">
              AWS EC2 Deployment & Container Management
            </p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        {!isLoggedIn ? (
          // Show login prompt when not logged in
          <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-6">
            <div className="text-center space-y-4">
              <h2 className="text-2xl font-semibold">Welcome to Inversion Deployer</h2>
              <p className="text-muted-foreground">
                Please login with your IAM Role ARN to get started
              </p>
            </div>
            <Button
              onClick={() => setLoginDialogOpen(true)}
              size="lg"
              className="gap-2"
            >
              Login with IAM Role ARN
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
            />
              <StatusCard
                isLoggedIn={isLoggedIn}
                instances={instances}
                selectedInstance={selectedInstance}
                onSelectInstance={setSelectedInstance}
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

            {/* Action Toolbar */}
            <ActionToolbar
              isLoggedIn={isLoggedIn}
              hasSelectedInstance={!!selectedInstance}
              repositoryHasImages={repositoryStatus?.hasImages ?? false}
              onRoleLogin={() => setLoginDialogOpen(true)}
              onRefresh={handleRefresh}
              onDeploy={handleDeploy}
              onTerminate={handleTerminate}
              onConnect={handleConnect}
            />

            {/* Progress & Logs */}
            <ProgressLogArea progress={progress} logs={logs} onClearLogs={clearLogs} />

            {/* File Transfer */}
            <FileTransferSection
              isConnected={isLoggedIn && !!selectedInstance}
              onUpload={handleUpload}
              onDownload={handleDownload}
            />

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

        {/* Login Dialog */}
        <RoleLoginDialog
          open={loginDialogOpen}
          required={!isLoggedIn}
          onOpenChange={(open) => {
            // Only allow closing if already logged in
            if (isLoggedIn) {
              setLoginDialogOpen(open);
            }
          }}
          onLogin={async (roleArn, externalId, region) => {
            await handleRoleLogin(roleArn, externalId, region);
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
