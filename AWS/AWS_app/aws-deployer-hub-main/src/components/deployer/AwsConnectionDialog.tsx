import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
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
import { cloudformationLogin, cloudformationVerify, listOrganizations, getOrganization } from '@/lib/api';
import { toast } from 'sonner';

interface AwsConnectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRoleArnReceived: (roleArn: string, accountId: string, externalId: string, region: string) => Promise<void>;
  required?: boolean;
  onHasNoOrg?: (hasNoOrg: boolean) => void; // Callback to notify parent when user has no org
}

export function AwsConnectionDialog({ 
  open, 
  onOpenChange, 
  onRoleArnReceived,
  required = false,
  onHasNoOrg
}: AwsConnectionDialogProps) {
  const navigate = useNavigate();
  const [step, setStep] = useState<'account' | 'verify'>('account');
  const [accountId, setAccountId] = useState('');
  const [region, setRegion] = useState('us-east-1');
  const [loading, setLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cloudFormationData, setCloudFormationData] = useState<any>(null);
  const [consoleOpened, setConsoleOpened] = useState(false);
  const [orgId, setOrgId] = useState<string | null>(null);
  const [organization, setOrganization] = useState<any>(null);
  const [hasNoOrg, setHasNoOrg] = useState(false);

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) {
      setStep('account');
      setAccountId('');
      setError(null);
      setCloudFormationData(null);
      setConsoleOpened(false);
      setOrgId(null);
      setOrganization(null);
      setHasNoOrg(false);
    }
  }, [open]);

  // Load user's organization when dialog opens
  useEffect(() => {
    if (open && !orgId) {
      listOrganizations()
        .then((response) => {
          if (response.organizations && response.organizations.length > 0) {
            // Use the user's owned org if they own one, otherwise use the first org
            const ownedOrg = response.organizations.find((org: any) => org.role === 'owner');
            const selectedOrg = ownedOrg || response.organizations[0];
            setOrgId(selectedOrg.org_id);
            
            // Load organization details to get default AWS account ID
            getOrganization(selectedOrg.org_id)
              .then((orgResponse) => {
                setOrganization(orgResponse.organization);
                
                // Auto-fill AWS account ID from organization's default if available
                if (orgResponse.organization.default_aws_account_id && !accountId) {
                  setAccountId(orgResponse.organization.default_aws_account_id);
                }
              })
              .catch(() => {
                // Ignore errors when loading org details
              });
          } else {
            setHasNoOrg(true);
            setError('You must be a member of an organization to connect AWS accounts. Please join or create an organization first.');
            // Notify parent component
            if (onHasNoOrg) {
              onHasNoOrg(true);
            }
          }
        })
        .catch((err) => {
          const errorMessage = err instanceof Error ? err.message : 'Failed to load organizations';
          setError(errorMessage);
        });
    }
  }, [open, orgId, accountId]);

  const handleAccountSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (!orgId) {
        setError('Organization ID is required. Please ensure you are a member of an organization.');
        setLoading(false);
        return;
      }

      // Check if organization has a default AWS account ID
      if (!organization?.default_aws_account_id) {
        setError('Your organization does not have a default AWS Account ID set. Please go to Organization Settings to set one before connecting.');
        toast.error('Organization AWS Account ID required');
        setLoading(false);
        return;
      }

      // Use organization's default AWS account ID
      const awsAccountIdToUse = organization.default_aws_account_id;
      
      // Validate account ID (12 digits)
      if (!awsAccountIdToUse.match(/^\d{12}$/)) {
        setError('Organization AWS Account ID must be exactly 12 digits');
        setLoading(false);
        return;
      }

      // Update accountId to match organization's default
      setAccountId(awsAccountIdToUse);

      const response = await cloudformationLogin(awsAccountIdToUse, region, orgId);
      setCloudFormationData(response);
      setStep('verify');
      toast.success('CloudFormation template ready!');
    } catch (err) {
      // Better error handling - extract message from error object
      let errorMessage = 'Failed to initialize AWS connection';
      if (err instanceof Error) {
        errorMessage = err.message;
      } else if (typeof err === 'object' && err !== null) {
        const errObj = err as any;
        errorMessage = errObj.detail || errObj.message || errObj.error || JSON.stringify(errObj);
      } else if (typeof err === 'string') {
        errorMessage = err;
      }
      setError(errorMessage);
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
    if (!orgId) {
      setError('Organization ID is required. Please ensure you are a member of an organization.');
      toast.error('Organization ID is required');
      return;
    }

    // Check if organization has a default AWS account ID
    if (!organization?.default_aws_account_id) {
      setError('Your organization does not have a default AWS Account ID set. Please go to Organization Settings to set one before verifying the connection.');
      toast.error('Organization AWS Account ID required');
      return;
    }

    // Only allow verification with the organization's default AWS account ID
    if (accountId !== organization.default_aws_account_id) {
      setError(`You can only verify connections using your organization's AWS Account ID (${organization.default_aws_account_id}). Please use the organization's AWS ID.`);
      toast.error('Must use organization AWS Account ID');
      return;
    }

    setError(null);
    setVerifying(true);

    try {
      const response = await cloudformationVerify(organization.default_aws_account_id, region, orgId);
      
      // Success! Call the callback with the session info
      // The role ARN is computed automatically, so we pass it from the response
      await onRoleArnReceived(response.role_arn, organization.default_aws_account_id, '', region);
      
      // Reset form on success
      setAccountId('');
      setStep('account');
      setCloudFormationData(null);
      setConsoleOpened(false);
      // Reload organization to refresh default AWS account ID if it was set
      if (orgId) {
        getOrganization(orgId)
          .then((orgResponse) => {
            setOrganization(orgResponse.organization);
          })
          .catch(() => {
            // Ignore errors
          });
      }
      handleDialogOpenChange(false);
      toast.success(`Connected to account ${response.account_id}!`);
    } catch (err) {
      // Better error handling - extract message from error object
      let errorMessage = 'Connection failed';
      if (err instanceof Error) {
        errorMessage = err.message;
      } else if (typeof err === 'object' && err !== null) {
        // Try to extract detail or message from error object
        const errObj = err as any;
        errorMessage = errObj.detail || errObj.message || errObj.error || JSON.stringify(errObj);
      } else if (typeof err === 'string') {
        errorMessage = err;
      }
      
      setError(errorMessage);
      toast.error(errorMessage);
    } finally {
      setVerifying(false);
    }
  };

  const handleDialogOpenChange = (newOpen: boolean) => {
    // Always allow closing - let the parent component decide
    // The parent can check hasNoOrg via the callback if needed
    onOpenChange(newOpen);
  };

  return (
    <Dialog 
      open={open} 
      onOpenChange={handleDialogOpenChange}
    >
      <DialogContent className="sm:max-w-[550px] max-h-[90vh] flex flex-col">
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
                    disabled={!!organization?.default_aws_account_id || loading}
                  />
                  <p className="text-xs text-muted-foreground">
                    {organization?.default_aws_account_id ? (
                      <>
                        Using your organization's AWS Account ID: <span className="font-semibold">{organization.default_aws_account_id}</span>
                        <span className="block mt-1 text-muted-foreground/80">
                          This value is set in your Organization Settings and cannot be changed here.
                        </span>
                      </>
                    ) : (
                      <>
                        Your 12-digit AWS Account ID
                        <span className="block mt-1 text-muted-foreground/80">
                          Note: You must set a default AWS Account ID in Organization Settings before connecting.
                        </span>
                      </>
                    )}
                  </p>
                  {!organization?.default_aws_account_id && (
                    <Alert className="mt-2">
                      <AlertTriangle className="h-4 w-4" />
                      <AlertDescription className="text-xs">
                        Your organization does not have a default AWS Account ID set. Please go to{' '}
                        <a href="/organization" className="underline font-semibold">Organization Settings</a> to set one before connecting.
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
                    {hasNoOrg && (
                      <div className="mt-3 flex gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            handleDialogOpenChange(false);
                            navigate('/organization');
                          }}
                        >
                          Go to Organizations
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => handleDialogOpenChange(false)}
                        >
                          Close
                        </Button>
                      </div>
                    )}
                  </Alert>
                )}
              </div>

              <DialogFooter>
                {(!required || hasNoOrg) && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      if (hasNoOrg) {
                        navigate('/organization');
                      }
                      handleDialogOpenChange(false);
                    }}
                    disabled={loading}
                  >
                    {hasNoOrg ? 'Go to Organizations' : 'Cancel'}
                  </Button>
                )}
                <Button type="submit" disabled={loading || !organization?.default_aws_account_id || hasNoOrg}>
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
              {!organization?.default_aws_account_id ? (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertDescription className="text-sm">
                    <strong>Organization AWS Account ID Required</strong>
                    <p className="mt-1 text-xs">
                      Your organization does not have a default AWS Account ID set. Please go to{' '}
                      <a href="/organization" className="underline font-semibold">Organization Settings</a> to set one before verifying the connection.
                    </p>
                  </AlertDescription>
                </Alert>
              ) : (
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
              )}

              {organization?.default_aws_account_id && (
                <Alert>
                  <InfoIcon className="h-4 w-4" />
                  <AlertDescription className="text-sm">
                    <strong>Using Organization AWS Account ID:</strong> {organization.default_aws_account_id}
                  </AlertDescription>
                </Alert>
              )}

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
                disabled={verifying || !organization?.default_aws_account_id}
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

