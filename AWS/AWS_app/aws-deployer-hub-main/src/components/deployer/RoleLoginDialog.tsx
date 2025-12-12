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
import { InfoIcon } from 'lucide-react';

interface RoleLoginDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLogin: (roleArn: string, externalId: string, region: string) => Promise<void>;
  required?: boolean; // If true, dialog cannot be closed without logging in
}

export function RoleLoginDialog({ open, onOpenChange, onLogin, required = false }: RoleLoginDialogProps) {
  const [roleArn, setRoleArn] = useState('');
  const [externalId, setExternalId] = useState('');
  const [region, setRegion] = useState('us-east-1');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await onLogin(roleArn, externalId, region);
      // Reset form on success
      setRoleArn('');
      setExternalId('');
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog 
      open={open} 
      onOpenChange={(newOpen) => {
        // If required, prevent closing (only allow if newOpen is true, i.e., opening)
        if (required && !newOpen) {
          // Prevent closing when required
          return;
        }
        onOpenChange(newOpen);
      }}
    >
      <DialogContent className={`sm:max-w-[500px] ${required ? '[&>button.absolute]:hidden' : ''}`}>
        <DialogHeader>
          <DialogTitle>Login with IAM Role ARN</DialogTitle>
          <DialogDescription>
            {required 
              ? "Login is required to use Inversion Deployer. Enter your IAM Role ARN to authenticate."
              : "Enter your IAM Role ARN to authenticate. The role must be configured to trust this application's AWS account."}
          </DialogDescription>
        </DialogHeader>
        
        <form onSubmit={handleSubmit}>
          <div className="space-y-4 py-4">
            <Alert>
              <InfoIcon className="h-4 w-4" />
              <AlertDescription className="text-xs">
                You need to create an IAM role in your AWS account with a trust policy that allows this application to assume it.
                The role ARN format is: arn:aws:iam::ACCOUNT_ID:role/ROLE_NAME
              </AlertDescription>
            </Alert>

            <div className="space-y-2">
              <Label htmlFor="roleArn">IAM Role ARN *</Label>
              <Input
                id="roleArn"
                placeholder="arn:aws:iam::123456789012:role/InversionDeployerRole"
                value={roleArn}
                onChange={(e) => setRoleArn(e.target.value)}
                required
                className="font-mono text-sm"
              />
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
                If your role requires an External ID, enter it here for additional security.
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
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
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
            <Button type="submit" disabled={loading || !roleArn}>
              {loading ? 'Logging in...' : 'Login'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

