import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { AWS_REGIONS } from '@/types/aws';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { InfoIcon, ExternalLink, CheckCircle2, Loader2, AlertTriangle } from 'lucide-react';
import { cloudformationLogin, cloudformationVerify, getCurrentUser, checkAwsAccount } from '@/lib/api';
import { toast } from 'sonner';

interface AwsConnectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRoleArnReceived: (roleArn: string, accountId: string, externalId: string, region: string) => Promise<void>;
  required?: boolean;
}

export function AwsConnectionDialog({ 
  open, 
  onOpenChange, 
  onRoleArnReceived,
  required = false 
}: AwsConnectionDialogProps) {
  const [step, setStep] = useState<'account' | 'verify'>('account');
  const [accountId, setAccountId] = useState('');
  const [region, setRegion] = useState('us-east-1');
  const [loading, setLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cloudFormationData, setCloudFormationData] = useState<any>(null);
  const [consoleOpened, setConsoleOpened] = useState(false);
  const [accountError, setAccountError] = useState<string | null>(null);

  // Auto-fill AWS account ID when dialog opens
  useEffect(() => {
    if (open && step === 'account' && !accountId) {
      getCurrentUser()
        .then((user) => {
          if (user.aws_account_id) {
            setAccountId(user.aws_account_id);
            // Check if this account is associated with someone else
            checkAwsAccount(user.aws_account_id)
              .then((result) => {
                if (result.associated_with_other_user) {
                  setAccountError(result.message);
                } else {
                  setAccountError(null);
                }
              })
              .catch(() => {
                // Ignore errors when checking
              });
          }
        })
        .catch(() => {
          // User not logged in or error - ignore
        });
    }
  }, [open, step, accountId]);

  // Check AWS account when user types it
  useEffect(() => {
    if (accountId && accountId.match(/^\d{12}$/)) {
      checkAwsAccount(accountId)
        .then((result) => {
          if (result.associated_with_other_user) {
            setAccountError(result.message);
          } else {
            setAccountError(null);
          }
        })
        .catch(() => {
          // Ignore errors
        });
    } else {
      setAccountError(null);
    }
  }, [accountId]);

  const handleAccountSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      // Validate account ID (12 digits)
      if (!accountId.match(/^\d{12}$/)) {
        setError('AWS Account ID must be exactly 12 digits');
        setLoading(false);
        return;
      }

      const response = await cloudformationLogin(accountId, region);
      setCloudFormationData(response);
      setStep('verify');
      toast.success('CloudFormation template ready!');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to initialize AWS connection');
    } finally {
      setLoading(false);
    }
  };

  const handleOpenConsole = () => {
    if (cloudFormationData?.cloudformation_console_url) {
      window.open(cloudFormationData.cloudformation_console_url, '_blank');
      setConsoleOpened(true);
      toast.success('Opening AWS CloudFormation Console...');
    }
  };

  const handleVerify = async () => {
    setError(null);
    setVerifying(true);

    try {
      const response = await cloudformationVerify(accountId, region);
      
      // Success! Call the callback with the session info
      // The role ARN is computed automatically, so we pass it from the response
      await onRoleArnReceived(response.role_arn, accountId, '', region);
      
      // Reset form on success
      setAccountId('');
      setStep('account');
      setCloudFormationData(null);
      setConsoleOpened(false);
      onOpenChange(false);
      toast.success(`Connected to account ${response.account_id}!`);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Connection failed';
      setError(errorMessage);
      toast.error(errorMessage);
    } finally {
      setVerifying(false);
    }
  };

  return (
    <Dialog 
      open={open} 
      onOpenChange={(newOpen) => {
        if (required && !newOpen) {
          return;
        }
        onOpenChange(newOpen);
      }}
    >
      <DialogContent className={`sm:max-w-[550px] max-h-[90vh] flex flex-col ${required ? '[&>button.absolute]:hidden' : ''}`}>
        {step === 'account' ? (
          <>
            <DialogHeader>
              <DialogTitle>Connect to AWS</DialogTitle>
              <DialogDescription>
                {required 
                  ? "Connect your AWS account to use Inversion Deployer. We'll help you set up the required IAM role via CloudFormation."
                  : "Enter your AWS Account ID to get started. We'll guide you through creating the necessary IAM role."}
              </DialogDescription>
            </DialogHeader>
            
            <form onSubmit={handleAccountSubmit} className="flex flex-col min-h-0">
              <div className="space-y-4 py-4 overflow-y-auto flex-1 min-h-0">
                <Alert>
                  <InfoIcon className="h-4 w-4" />
                  <AlertDescription className="text-sm">
                    We'll open the AWS CloudFormation Console where you can deploy an IAM role stack. 
                    The stack creation page will be pre-filled with all necessary values.
                  </AlertDescription>
                </Alert>

                <div className="space-y-2">
                  <Label htmlFor="accountId">AWS Account ID *</Label>
                  <Input
                    id="accountId"
                    placeholder="123456789012"
                    value={accountId}
                    onChange={(e) => setAccountId(e.target.value.replace(/\D/g, ''))}
                    required
                    maxLength={12}
                    className="font-mono text-sm"
                  />
                  <p className="text-xs text-muted-foreground">
                    Your 12-digit AWS Account ID
                  </p>
                  {accountError && (
                    <Alert variant="destructive" className="mt-2">
                      <AlertTriangle className="h-4 w-4" />
                      <AlertDescription className="text-xs">
                        {accountError}
                      </AlertDescription>
                    </Alert>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="region">AWS Region</Label>
                  <Select value={region} onValueChange={setRegion}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {AWS_REGIONS.map((r) => (
                        <SelectItem key={r.value} value={r.value}>
                          {r.label} ({r.value})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {error && (
                  <Alert variant="destructive" className="max-h-[200px] overflow-y-auto">
                    <AlertDescription className="break-words">{error}</AlertDescription>
                  </Alert>
                )}
              </div>

              <DialogFooter>
                {!required && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => onOpenChange(false)}
                    disabled={loading}
                  >
                    Cancel
                  </Button>
                )}
                <Button type="submit" disabled={loading || !accountId || accountId.length !== 12 || !!accountError}>
                  {loading ? 'Preparing...' : 'Continue'}
                </Button>
              </DialogFooter>
            </form>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Deploy IAM Role Stack</DialogTitle>
              <DialogDescription>
                Deploy the CloudFormation stack in AWS Console, then verify the connection automatically.
              </DialogDescription>
            </DialogHeader>
            
            <div className="space-y-4 py-4 overflow-y-auto flex-1 min-h-0">
              <Alert>
                <InfoIcon className="h-4 w-4" />
                <AlertDescription className="text-sm">
                  <strong>Quick steps:</strong>
                  <ol className="list-decimal list-inside mt-2 space-y-1 text-xs">
                    <li>Click "Open AWS Console" below - the CloudFormation quick create page will open</li>
                    <li>All values are already pre-filled (template, stack name, parameters)</li>
                    <li>Simply click the "Create stack" button</li>
                    <li>Wait for stack creation to complete (usually 30-60 seconds)</li>
                    <li>Return here and click "Verify Connection" - we'll automatically connect!</li>
                  </ol>
                </AlertDescription>
              </Alert>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label>CloudFormation Stack</Label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleOpenConsole}
                    className="gap-2"
                    disabled={verifying}
                  >
                    <ExternalLink className="h-4 w-4" />
                    {consoleOpened ? 'Reopen Console' : 'Open AWS Console'}
                  </Button>
                </div>
                
                {consoleOpened && (
                  <Alert className="bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800">
                    <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
                    <AlertDescription className="text-xs text-green-800 dark:text-green-200">
                      AWS Console opened. Deploy the stack, then click "Verify Connection" below.
                    </AlertDescription>
                  </Alert>
                )}

                <div className="text-xs text-muted-foreground space-y-1">
                  <p><strong>Stack Name:</strong> <code className="bg-muted px-1 rounded">{cloudFormationData?.stack_name}</code></p>
                  <p><strong>Template URL:</strong> <code className="bg-muted px-1 rounded text-[10px] break-all">{cloudFormationData?.template_s3_url}</code></p>
                  <p><strong>Expected Role ARN:</strong> <code className="bg-muted px-1 rounded">{cloudFormationData?.role_arn_format}</code></p>
                </div>
              </div>

              {verifying && (
                <Alert>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <AlertDescription className="text-sm">
                    <strong>Connecting...</strong>
                    <p className="text-xs mt-1">
                      Attempting to connect to your AWS account. This may take up to 2 minutes if the stack is still creating.
                    </p>
                  </AlertDescription>
                </Alert>
              )}

              {error && (
                <Alert variant="destructive" className="max-h-[200px] overflow-y-auto">
                  <AlertDescription className="text-sm whitespace-pre-line break-words">{error}</AlertDescription>
                </Alert>
              )}
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setStep('account');
                  setCloudFormationData(null);
                  setConsoleOpened(false);
                  setVerifying(false);
                  setError(null);
                }}
                disabled={verifying}
              >
                Back
              </Button>
              <Button 
                type="button"
                onClick={handleVerify}
                disabled={verifying}
              >
                {verifying ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Connecting...
                  </>
                ) : (
                  'Verify Connection'
                )}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

