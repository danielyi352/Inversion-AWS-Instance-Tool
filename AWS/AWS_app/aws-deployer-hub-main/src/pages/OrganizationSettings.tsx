import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { ArrowLeft, Save, Building2, Users, Plus, Trash2, Mail } from 'lucide-react';
import { toast } from 'sonner';
import { 
  getOrganization,
  updateOrganization,
  listOrgMembers,
  inviteUser,
  updateMemberRole,
  removeMember,
  deleteOrganization,
  getCurrentUser,
  type Organization,
  type UpdateOrgRequest,
  type OrganizationMember,
  type InviteUserRequest
} from '@/lib/api';
import { AppHeader } from '@/components/AppHeader';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';

const OrganizationSettings = () => {
  const navigate = useNavigate();
  const { orgId } = useParams<{ orgId: string }>();
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [currentUser, setCurrentUser] = useState<any>(null);
  
  // Form state
  const [orgName, setOrgName] = useState('');
  const [orgDescription, setOrgDescription] = useState('');
  const [awsAccountId, setAwsAccountId] = useState('');
  
  // Members state
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [inviteDialogOpen, setInviteDialogOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<'member' | 'admin'>('member');
  const [removeMemberDialogOpen, setRemoveMemberDialogOpen] = useState(false);
  const [memberToRemove, setMemberToRemove] = useState<OrganizationMember | null>(null);
  const [deleteOrgDialogOpen, setDeleteOrgDialogOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    // Check if user is authenticated
    const userSessionId = localStorage.getItem('user_session_id');
    
    if (!userSessionId) {
      navigate('/login');
      return;
    }

    if (orgId) {
      loadOrganization();
      loadMembers();
      loadCurrentUser();
    }
  }, [orgId, navigate]);
  
  const loadCurrentUser = async () => {
    try {
      const user = await getCurrentUser();
      setCurrentUser(user);
    } catch (error) {
      console.error('Failed to load current user:', error);
    }
  };
  
  const loadMembers = async () => {
    if (!orgId) return;
    
    try {
      const response = await listOrgMembers(orgId);
      setMembers(response.members);
    } catch (error: any) {
      toast.error(`Failed to load members: ${error.message}`);
    }
  };

  const loadOrganization = async () => {
    if (!orgId) return;
    
    try {
      setLoading(true);
      const response = await getOrganization(orgId);
      const org = response.organization;
      setOrganization(org);
      setOrgName(org.name);
      setOrgDescription(org.description || '');
      setAwsAccountId(org.default_aws_account_id || '');
    } catch (error: any) {
      toast.error(`Failed to load organization: ${error.message}`);
      navigate('/organization');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!orgId || !organization) {
      return;
    }

    // Validate AWS account ID format if provided
    if (awsAccountId && (awsAccountId.length !== 12 || !/^\d+$/.test(awsAccountId))) {
      toast.error('AWS Account ID must be exactly 12 digits');
      return;
    }

    // Validate organization name
    if (!orgName.trim()) {
      toast.error('Organization name is required');
      return;
    }

    try {
      setSaving(true);
      const updateData: UpdateOrgRequest = {
        name: orgName.trim(),
        description: orgDescription.trim() || undefined,
        default_aws_account_id: awsAccountId.trim() || undefined,
      };
      
      const response = await updateOrganization(orgId, updateData);
      toast.success('Organization settings updated successfully');
      setOrganization(response.organization);
      // Update form fields with new data
      setOrgName(response.organization.name);
      setOrgDescription(response.organization.description || '');
      setAwsAccountId(response.organization.default_aws_account_id || '');
    } catch (error: any) {
      toast.error(`Failed to update organization: ${error.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleInviteUser = async () => {
    if (!orgId) {
      return;
    }

    if (!inviteEmail.trim()) {
      toast.error('Email is required');
      return;
    }

    try {
      const inviteData: InviteUserRequest = {
        email: inviteEmail.trim(),
        role: inviteRole,
      };
      
      await inviteUser(orgId, inviteData);
      toast.success('Invitation sent successfully!');
      setInviteDialogOpen(false);
      setInviteEmail('');
      setInviteRole('member');
      await loadMembers();
    } catch (error: any) {
      const errorMessage = error.message || 'Failed to send invitation';
      toast.error(errorMessage);
    }
  };

  const handleUpdateMemberRole = async (userId: string, newRole: 'admin' | 'member') => {
    if (!orgId) {
      return;
    }

    try {
      await updateMemberRole(orgId, userId, newRole);
      toast.success('Member role updated successfully');
      await loadMembers();
    } catch (error: any) {
      toast.error(`Failed to update member role: ${error.message}`);
    }
  };

  const handleRemoveMember = async () => {
    if (!orgId || !memberToRemove) {
      return;
    }

    try {
      await removeMember(orgId, memberToRemove.user_id);
      toast.success('Member removed successfully');
      setRemoveMemberDialogOpen(false);
      setMemberToRemove(null);
      await loadMembers();
    } catch (error: any) {
      toast.error(`Failed to remove member: ${error.message}`);
    }
  };

  const handleDeleteOrganization = async () => {
    if (!orgId) {
      return;
    }

    try {
      setDeleting(true);
      await deleteOrganization(orgId);
      toast.success('Organization deleted successfully');
      navigate('/organization');
    } catch (error: any) {
      toast.error(`Failed to delete organization: ${error.message}`);
    } finally {
      setDeleting(false);
      setDeleteOrgDialogOpen(false);
    }
  };

  const getRoleBadgeVariant = (role: string) => {
    switch (role) {
      case 'owner':
        return 'default';
      case 'admin':
        return 'secondary';
      default:
        return 'outline';
    }
  };

  const isOwner = organization?.owner_id === currentUser?.user_id;
  const isAdmin = members.find(m => m.user_id === currentUser?.user_id)?.role === 'admin' || isOwner;

  if (loading) {
    return (
      <div className="min-h-screen bg-background">
        <AppHeader />
        <div className="p-8">
          <div className="max-w-4xl mx-auto">
            <p className="text-muted-foreground">Loading organization settings...</p>
          </div>
        </div>
      </div>
    );
  }

  if (!organization) {
    return (
      <div className="min-h-screen bg-background">
        <AppHeader />
        <div className="p-8">
          <div className="max-w-4xl mx-auto">
            <p className="text-muted-foreground">Organization not found</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <div className="p-8">
        <div className="max-w-4xl mx-auto">
          {/* Header */}
          <div className="mb-6 flex items-center gap-4">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => navigate('/organization')}
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <h1 className="text-4xl font-bold mb-2">Organization Settings</h1>
              <p className="text-muted-foreground">Manage your organization details and AWS account</p>
            </div>
          </div>

          {/* Organization Details Card */}
          <Card className="mb-6">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <Building2 className="h-5 w-5" />
                    Organization Details
                  </CardTitle>
                  <CardDescription>
                    Update your organization's name and description
                  </CardDescription>
                </div>
                {isOwner && (
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setDeleteOrgDialogOpen(true)}
                    className="gap-2"
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete Organization
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label htmlFor="org-name">Organization Name *</Label>
                <Input
                  id="org-name"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  placeholder="My Organization"
                />
              </div>
              <div>
                <Label htmlFor="org-description">Description</Label>
                <Textarea
                  id="org-description"
                  value={orgDescription}
                  onChange={(e) => setOrgDescription(e.target.value)}
                  placeholder="Optional description"
                  rows={4}
                />
              </div>
            </CardContent>
          </Card>

          {/* AWS Account Settings Card */}
          <Card className="mb-6">
            <CardHeader>
              <CardTitle>AWS Account Settings</CardTitle>
              <CardDescription>
                Set a dedicated AWS account ID for this organization. When members connect via AWS, this account will be used automatically.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label htmlFor="aws-account-id">Default AWS Account ID (12 digits)</Label>
                <Input
                  id="aws-account-id"
                  value={awsAccountId}
                  onChange={(e) => setAwsAccountId(e.target.value.replace(/\D/g, '').slice(0, 12))}
                  placeholder="123456789012"
                  maxLength={12}
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Leave empty to allow members to use their own AWS account IDs. When set, all members will use this account when connecting via AWS.
                </p>
              </div>
              {awsAccountId && (
                <div className="p-3 bg-muted rounded-lg">
                  <p className="text-sm font-medium">Current AWS Account ID:</p>
                  <p className="text-sm text-muted-foreground font-mono">{awsAccountId}</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Members Management Card */}
          <Card className="mb-6">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <Users className="h-5 w-5" />
                    Members Management
                  </CardTitle>
                  <CardDescription>
                    Invite, manage roles, and remove members from your organization
                  </CardDescription>
                </div>
                {isAdmin && (
                  <Dialog open={inviteDialogOpen} onOpenChange={setInviteDialogOpen}>
                    <DialogTrigger asChild>
                      <Button>
                        <Plus className="h-4 w-4 mr-2" />
                        Invite Member
                      </Button>
                    </DialogTrigger>
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>Invite Member</DialogTitle>
                        <DialogDescription>
                          Invite a user to join this organization.
                        </DialogDescription>
                      </DialogHeader>
                      <div className="space-y-4">
                        <div>
                          <Label htmlFor="invite-email">Email *</Label>
                          <Input
                            id="invite-email"
                            type="email"
                            value={inviteEmail}
                            onChange={(e) => setInviteEmail(e.target.value)}
                            placeholder="user@example.com"
                          />
                        </div>
                        <div>
                          <Label htmlFor="invite-role">Role</Label>
                          <Select value={inviteRole} onValueChange={(value: 'member' | 'admin') => setInviteRole(value)}>
                            <SelectTrigger>
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="member">Member</SelectItem>
                              <SelectItem value="admin">Admin</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                        <Button onClick={handleInviteUser} className="w-full">
                          Send Invitation
                        </Button>
                      </div>
                    </DialogContent>
                  </Dialog>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {members.length === 0 ? (
                <p className="text-sm text-muted-foreground">No members yet.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead>Joined</TableHead>
                      {isAdmin && <TableHead className="text-right">Actions</TableHead>}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {members.map((member) => {
                      const isOrgOwner = member.user_id === organization?.owner_id;
                      const isCurrentUser = member.user_id === currentUser?.user_id;
                      const canEdit = isAdmin && !isOrgOwner && !isCurrentUser;
                      
                      return (
                        <TableRow key={member.user_id}>
                          <TableCell>{member.name || 'N/A'}</TableCell>
                          <TableCell>{member.email}</TableCell>
                          <TableCell>
                            {isOrgOwner ? (
                              <Badge variant="default">Owner</Badge>
                            ) : isAdmin && canEdit ? (
                              <Select
                                value={member.role}
                                onValueChange={(value: 'admin' | 'member') => 
                                  handleUpdateMemberRole(member.user_id, value)
                                }
                              >
                                <SelectTrigger className="w-32">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="member">Member</SelectItem>
                                  <SelectItem value="admin">Admin</SelectItem>
                                </SelectContent>
                              </Select>
                            ) : (
                              <Badge variant={getRoleBadgeVariant(member.role)}>
                                {member.role}
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell>
                            {new Date(member.joined_at).toLocaleDateString()}
                          </TableCell>
                          {isAdmin && (
                            <TableCell className="text-right">
                              {canEdit && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => {
                                    setMemberToRemove(member);
                                    setRemoveMemberDialogOpen(true);
                                  }}
                                >
                                  <Trash2 className="h-4 w-4 text-destructive" />
                                </Button>
                              )}
                            </TableCell>
                          )}
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Save Button */}
          <div className="flex justify-end gap-4">
            <Button
              variant="outline"
              onClick={() => navigate('/organization')}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={saving}
            >
              <Save className="h-4 w-4 mr-2" />
              {saving ? 'Saving...' : 'Save Changes'}
            </Button>
          </div>

          {/* Remove Member Alert Dialog */}
          <AlertDialog open={removeMemberDialogOpen} onOpenChange={setRemoveMemberDialogOpen}>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Remove Member</AlertDialogTitle>
                <AlertDialogDescription>
                  Are you sure you want to remove <strong>{memberToRemove?.name || memberToRemove?.email}</strong> from this organization? 
                  They will lose access to all AWS connections and resources associated with this organization.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel onClick={() => setMemberToRemove(null)}>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={handleRemoveMember} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                  Remove Member
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>

          {/* Delete Organization Alert Dialog */}
          {isOwner && (
            <AlertDialog open={deleteOrgDialogOpen} onOpenChange={setDeleteOrgDialogOpen}>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete Organization</AlertDialogTitle>
                  <AlertDialogDescription>
                    <p className="mb-2">
                      Are you sure you want to delete <strong>{organization.name}</strong>? This action cannot be undone.
                    </p>
                    <p className="text-sm text-muted-foreground">
                      This will:
                    </p>
                    <ul className="list-disc list-inside text-sm text-muted-foreground mt-1 space-y-1">
                      <li>Remove all members from the organization</li>
                      <li>Delete all pending invitations</li>
                      <li>Delete all AWS connections associated with this organization</li>
                      <li>Permanently delete the organization</li>
                    </ul>
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
                  <AlertDialogAction 
                    onClick={handleDeleteOrganization} 
                    disabled={deleting}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  >
                    {deleting ? 'Deleting...' : 'Delete Organization'}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      </div>
    </div>
  );
};

export default OrganizationSettings;
