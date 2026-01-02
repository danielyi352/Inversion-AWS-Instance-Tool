import { useState } from 'react';
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
import { InfoIcon, ExternalLink, Copy, Check } from 'lucide-react';
import { cloudformationLogin } from '@/lib/api';
import { toast } from 'sonner';

interface CloudFormationLoginDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRoleArnReceived: (roleArn: string, accountId: string, externalId: string, region: string) => Promise<void>;
  required?: boolean;
}

export function CloudFormationLoginDialog({ 
  open, 
  onOpenChange, 
  onRoleArnReceived,
  required = false 
}: CloudFormationLoginDialogProps) {
  const [step, setStep] = useState<'account' | 'arn'>('account');
  const [accountId, setAccountId] = useState('');
  const [region, setRegion] = useState('us-east-1');
  const [roleArn, setRoleArn] = useState('');
  const [externalId, setExternalId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cloudFormationData, setCloudFormationData] = useState<any>(null);
  const [copied, setCopied] = useState(false);

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
      
      // Automatically redirect to AWS Console
      if (response.cloudformation_console_url) {
        window.open(response.cloudformation_console_url, '_blank');
        toast.success('Opening AWS CloudFormation Console...');
      }
      
      setStep('arn');
      toast.info('Deploy the stack in AWS Console, then return here with the Role ARN.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get CloudFormation template');
    } finally {
      setLoading(false);
    }
  };

  const handleArnSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await onRoleArnReceived(roleArn, accountId, externalId, region);
      // Reset form on success
      setAccountId('');
      setRoleArn('');
      setExternalId('');
      setStep('account');
      setCloudFormationData(null);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  const copyTemplate = () => {
    if (cloudFormationData?.template_json) {
      navigator.clipboard.writeText(cloudFormationData.template_json);
      setCopied(true);
      toast.success('CloudFormation template copied to clipboard!');
      setTimeout(() => setCopied(false), 2000);
    } else if (cloudFormationData?.template) {
      navigator.clipboard.writeText(JSON.stringify(cloudFormationData.template, null, 2));
      setCopied(true);
      toast.success('CloudFormation template copied to clipboard!');
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const openCloudFormationConsole = () => {
    // Try quick-create URL first, fallback to simple console URL
    const url = cloudFormationData?.cloudformation_quick_create_url || 
                cloudFormationData?.cloudformation_console_url;
    if (url) {
      window.open(url, '_blank');
    }
  };

  const downloadTemplate = () => {
    if (cloudFormationData?.template_json) {
      const blob = new Blob([cloudFormationData.template_json], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `inversion-deployer-role-${accountId}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success('Template downloaded!');
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
      <DialogContent className={`sm:max-w-[600px] max-h-[90vh] flex flex-col ${required ? '[&>button.absolute]:hidden' : ''}`}>
        {step === 'account' ? (
          <>
            <DialogHeader>
              <DialogTitle>Login with AWS Account</DialogTitle>
              <DialogDescription>
                {required 
                  ? "Login is required to use Inversion Deployer. Enter your AWS Account ID to get started."
                  : "Enter your AWS Account ID. We'll provide a CloudFormation template to create the necessary IAM role."}
              </DialogDescription>
            </DialogHeader>
            
            <form onSubmit={handleAccountSubmit} className="flex flex-col min-h-0">
              <div className="space-y-4 py-4 overflow-y-auto flex-1 min-h-0">
                <Alert>
                  <InfoIcon className="h-4 w-4" />
                  <AlertDescription className="text-xs">
                    You'll be redirected to AWS CloudFormation Console to deploy an IAM role. 
                    After deployment, you'll need to provide the Role ARN from the stack outputs.
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
                          {r.value}
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
                <Button type="submit" disabled={loading || !accountId || accountId.length !== 12}>
                  {loading ? 'Getting template...' : 'Continue'}
                </Button>
              </DialogFooter>
            </form>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Deploy CloudFormation Stack</DialogTitle>
              <DialogDescription>
                Deploy the IAM role stack in AWS CloudFormation, then enter the Role ARN from the stack outputs.
              </DialogDescription>
            </DialogHeader>
            
            <form onSubmit={handleArnSubmit} className="flex flex-col min-h-0">
              <div className="space-y-4 py-4 overflow-y-auto flex-1 min-h-0">
                <Alert>
                  <InfoIcon className="h-4 w-4" />
                  <AlertDescription className="text-xs">
                    {cloudFormationData?.instructions}
                  </AlertDescription>
                </Alert>

                <Alert>
                  <InfoIcon className="h-4 w-4" />
                  <AlertDescription className="text-sm">
                    <strong>Next steps:</strong>
                    <ol className="list-decimal list-inside mt-2 space-y-1 text-xs">
                      <li>In the AWS Console that opened, select "Template is ready"</li>
                      <li>Choose "Upload a template file"</li>
                      <li>Copy the template below or download it, then paste/upload it</li>
                      <li>Stack name: <code className="bg-muted px-1 rounded">{cloudFormationData?.stack_name}</code></li>
                      <li>Click "Create stack" and wait for it to complete</li>
                      <li>Go to the "Outputs" tab and copy the RoleArn value</li>
                      <li>Return here and paste the Role ARN below</li>
                    </ol>
                  </AlertDescription>
                </Alert>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label>CloudFormation Template</Label>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={copyTemplate}
                      >
                        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                        {copied ? 'Copied' : 'Copy'}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={downloadTemplate}
                      >
                        Download
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={openCloudFormationConsole}
                      >
                        <ExternalLink className="h-4 w-4 mr-2" />
                        Open Console
                      </Button>
                    </div>
                  </div>
                  <div className="border rounded-md p-3 bg-muted max-h-48 overflow-auto">
                    <pre className="text-xs font-mono whitespace-pre-wrap">
                      {cloudFormationData?.template_json || JSON.stringify(cloudFormationData?.template, null, 2)}
                    </pre>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Expected Role ARN: <code className="bg-muted px-1 rounded">{cloudFormationData?.role_arn_format}</code>
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="roleArn">IAM Role ARN *</Label>
                  <Input
                    id="roleArn"
                    placeholder="arn:aws:iam::123456789012:role/InversionDeployerRole-123456789012"
                    value={roleArn}
                    onChange={(e) => setRoleArn(e.target.value)}
                    required
                    className="font-mono text-sm"
                  />
                  <p className="text-xs text-muted-foreground">
                    Copy this from the CloudFormation stack Outputs tab after deployment
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="externalId">External ID (Optional)</Label>
                  <Input
                    id="externalId"
                    placeholder="Your unique external ID"
                    value={externalId}
                    onChange={(e) => setExternalId(e.target.value)}
                    className="font-mono text-sm"
                  />
                  <p className="text-xs text-muted-foreground">
                    If you specified an External ID in the CloudFormation template, enter it here.
                  </p>
                </div>

                {error && (
                  <Alert variant="destructive" className="max-h-[200px] overflow-y-auto">
                    <AlertDescription className="break-words">{error}</AlertDescription>
                  </Alert>
                )}
              </div>

              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setStep('account')}
                  disabled={loading}
                >
                  Back
                </Button>
                <Button type="submit" disabled={loading || !roleArn}>
                  {loading ? 'Logging in...' : 'Complete Login'}
                </Button>
              </DialogFooter>
            </form>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

