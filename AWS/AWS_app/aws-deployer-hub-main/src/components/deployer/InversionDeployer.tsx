import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { useAwsConfig } from '@/hooks/useAwsConfig';
import { AwsConfigCard } from './AwsConfigCard';
import { StatusCard } from './StatusCard';
import { ActionToolbar } from './ActionToolbar';
import { ProgressLogArea } from './ProgressLogArea';
import { FileTransferSection } from './FileTransferSection';

export function InversionDeployer() {
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
    handleSsoLogin,
    handleRefresh,
    handleDeploy,
    handleTerminate,
    handleConnect,
    handleUpload,
    handleDownload,
  } = useAwsConfig();

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
          <p className="text-sm text-muted-foreground">
            AWS EC2 Deployment & Container Management
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        <div className="space-y-8">
          {/* Top Panels */}
          <div className="grid gap-6 lg:grid-cols-2">
            <AwsConfigCard
              config={config}
              onConfigChange={updateConfig}
              ecrRepositories={metadata.repositories}
              keyPairs={metadata.keyPairs}
              securityGroups={metadata.securityGroups}
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
            onSsoLogin={handleSsoLogin}
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
      </main>
    </div>
  );
}
