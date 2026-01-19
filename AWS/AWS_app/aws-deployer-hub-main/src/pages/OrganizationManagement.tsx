import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { 
  Dialog, 
  DialogContent, 
  DialogDescription, 
  DialogHeader, 
  DialogTitle, 
  DialogTrigger 
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { 
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { ArrowLeft, Plus, Mail, Users, Building2, Settings } from 'lucide-react';
import { toast } from 'sonner';
import { 
  getCurrentUser, 
  listOrganizations, 
  createOrganization, 
  inviteUser, 
  listOrgMembers,
  listInvitations,
  acceptInvitation,
  rejectInvitation,
  leaveOrganization,
  type Organization,
  type OrganizationMember,
  type InviteUserRequest
} from '@/lib/api';
import { AppHeader } from '@/components/AppHeader';

const OrganizationManagement = () => {
  const navigate = useNavigate();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selectedOrg, setSelectedOrg] = useState<Organization | null>(null);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [invitations, setInvitations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [inviteDialogOpen, setInviteDialogOpen] = useState(false);
  const [pendingInviteDialogOpen, setPendingInviteDialogOpen] = useState(false);
  const [pendingInviteEmail, setPendingInviteEmail] = useState('');
  const [orgName, setOrgName] = useState('');
  const [orgDescription, setOrgDescription] = useState('');
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<'member' | 'admin'>('member');
  const [currentUser, setCurrentUser] = useState<any>(null);
  const [leaveDialogOpen, setLeaveDialogOpen] = useState(false);

  useEffect(() => {
    // Check if user is authenticated
    const userSessionId = localStorage.getItem('user_session_id');
    
    if (!userSessionId) {
      navigate('/login');
      return;
    }

    loadData();
    loadCurrentUser();
  }, [navigate]);

  const loadCurrentUser = async () => {
    try {
      const user = await getCurrentUser();
      setCurrentUser(user);
    } catch (error) {
      console.error('Failed to load current user:', error);
    }
  };

  const loadData = async () => {
    try {
      setLoading(true);
      const [orgsResponse, invitationsResponse] = await Promise.all([
        listOrganizations(),
        listInvitations().catch((error) => {
          console.error('Failed to load invitations:', error);
          // Don't show error toast for invitations, just log it
          return { status: 'ok', invitations: [] };
        })
      ]);
      
      setOrganizations(orgsResponse.organizations);
      setInvitations(invitationsResponse.invitations || []);
      
      // Debug: Log invitations
      console.log('Loaded invitations:', invitationsResponse.invitations);
      
      // Select first org if available (or user's owned org if they own one)
      if (orgsResponse.organizations.length > 0 && !selectedOrg) {
        // If user owns an org, select that one, otherwise select first
        const ownedOrg = orgsResponse.organizations.find(org => org.role === 'owner');
        setSelectedOrg(ownedOrg || orgsResponse.organizations[0]);
      }
    } catch (error: any) {
      toast.error(`Failed to load organizations: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Check if user already owns an organization
  const ownsOrganization = organizations.some(org => org.role === 'owner');
  
  // Check if user is a member of any organization (not just owner)
  const isMemberOfOrg = organizations.length > 0;
  
  // Check if current user is the owner of the selected org
  const isOwnerOfSelectedOrg = selectedOrg?.role === 'owner';

  useEffect(() => {
    if (selectedOrg) {
      loadMembers(selectedOrg.org_id);
    }
  }, [selectedOrg]);

  const loadMembers = async (orgId: string) => {
    try {
      const response = await listOrgMembers(orgId);
      setMembers(response.members);
    } catch (error: any) {
      toast.error(`Failed to load members: ${error.message}`);
    }
  };

  const handleCreateOrg = async () => {
    if (!orgName.trim()) {
      toast.error('Organization name is required');
      return;
    }

    if (ownsOrganization) {
      toast.error('You can only create one organization. You already own an organization.');
      return;
    }

    try {
      const response = await createOrganization({
        name: orgName.trim(),
        description: orgDescription.trim() || undefined,
      });
      
      toast.success('Organization created successfully!');
      setCreateDialogOpen(false);
      setOrgName('');
      setOrgDescription('');
      await loadData();
      setSelectedOrg(response.organization);
    } catch (error: any) {
      const errorMessage = error.message || 'Failed to create organization';
      toast.error(errorMessage);
    }
  };

  const handleInviteUser = async () => {
    if (!selectedOrg) {
      toast.error('Please select an organization first');
      return;
    }

    if (!inviteEmail.trim()) {
      toast.error('Email is required');
      return;
    }

    try {
      const inviteData = {
        email: inviteEmail.trim(),
        role: inviteRole,
      };
      console.log('Sending invitation:', inviteData);
      
      await inviteUser(selectedOrg.org_id, inviteData);
      
      toast.success('Invitation sent successfully!');
      setInviteDialogOpen(false);
      setInviteEmail('');
      setInviteRole('member');
      await loadData();
    } catch (error: any) {
      const errorMessage = error.message || 'Failed to send invitation';
      console.error('Invite error:', error);
      
      // Check if it's a pending invitation error
      if (errorMessage.toLowerCase().includes('already pending') || 
          errorMessage.toLowerCase().includes('invitation is already pending')) {
        setPendingInviteEmail(inviteEmail.trim());
        setPendingInviteDialogOpen(true);
      } else {
        toast.error(errorMessage);
      }
    }
  };

  const handleAcceptInvitation = async (token: string) => {
    try {
      await acceptInvitation(token);
      toast.success('Invitation accepted!');
      await loadData();
    } catch (error: any) {
      toast.error(`Failed to accept invitation: ${error.message}`);
    }
  };

  const handleRejectInvitation = async (token: string) => {
    try {
      await rejectInvitation(token);
      toast.success('Invitation rejected');
      await loadData();
    } catch (error: any) {
      toast.error(`Failed to reject invitation: ${error.message}`);
    }
  };

  const handleLeaveOrganization = async () => {
    if (!selectedOrg) {
      return;
    }

    try {
      await leaveOrganization(selectedOrg.org_id);
      toast.success('Successfully left the organization');
      setLeaveDialogOpen(false);
      await loadData();
      // Clear selected org and select first available if any
      if (organizations.length > 1) {
        const remainingOrgs = organizations.filter(org => org.org_id !== selectedOrg.org_id);
        setSelectedOrg(remainingOrgs[0] || null);
      } else {
        setSelectedOrg(null);
      }
    } catch (error: any) {
      toast.error(`Failed to leave organization: ${error.message}`);
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

  // Show loading state until data is loaded
  if (loading) {
    return (
      <div className="min-h-screen bg-background">
        <AppHeader />
        <div className="p-8">
          <div className="max-w-6xl mx-auto">
            <div className="mb-6 flex items-center gap-4">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => navigate('/dashboard')}
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <div>
                <h1 className="text-4xl font-bold mb-2">Organization Management</h1>
                <p className="text-muted-foreground">Manage your teams and invite members</p>
              </div>
            </div>
            <div className="flex items-center justify-center py-12">
              <div className="text-center">
                <p className="text-muted-foreground">Loading organizations...</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <div className="p-8">
        <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-6 flex items-center gap-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => navigate('/dashboard')}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-4xl font-bold mb-2">Organization Management</h1>
            <p className="text-muted-foreground">Manage your teams and invite members</p>
          </div>
        </div>

        {/* Pending Invitations - Hide if no invitations and user is a member */}
        {(!isMemberOfOrg || invitations.length > 0) && (
        <Card className={`mb-6 ${invitations.length > 0 ? 'border-primary' : ''}`}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Mail className="h-5 w-5" />
              Pending Invitations
              {invitations.length > 0 && (
                <Badge variant="secondary" className="ml-2">{invitations.length}</Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {invitations.length > 0 ? (
              <div className="space-y-2">
                {invitations.map((inv) => (
                  <div key={inv.token} className="flex items-center justify-between p-3 bg-muted rounded-lg">
                    <div>
                      <p className="font-medium">{inv.organization_name}</p>
                      <p className="text-sm text-muted-foreground">Role: {inv.role}</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        Expires: {new Date(inv.expires_at).toLocaleDateString()}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleRejectInvitation(inv.token)}
                      >
                        Reject
                      </Button>
                      <Button
                        size="sm"
                        onClick={() => handleAcceptInvitation(inv.token)}
                      >
                        Accept
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-4">
                <p className="text-sm text-muted-foreground">No pending invitations</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Invitations are sent to your account email address
                </p>
              </div>
            )}
          </CardContent>
        </Card>
        )}

        <div className={`grid grid-cols-1 gap-6 ${isMemberOfOrg ? 'lg:grid-cols-1' : 'lg:grid-cols-3'}`}>
          {/* Organizations List - Only show if user is not a member of any organization */}
          {!isMemberOfOrg && (
            <div className="lg:col-span-1">
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="flex items-center gap-2">
                      <Building2 className="h-5 w-5" />
                      Organizations
                    </CardTitle>
                    <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
                      <DialogTrigger asChild>
                        <Button size="sm" variant="outline">
                          <Plus className="h-4 w-4 mr-1" />
                          New
                        </Button>
                      </DialogTrigger>
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>Create Organization</DialogTitle>
                        <DialogDescription>
                          Create a new organization to share AWS accounts with your team.
                        </DialogDescription>
                      </DialogHeader>
                      <div className="space-y-4">
                        <div>
                          <Label htmlFor="org-name">Name *</Label>
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
                            rows={3}
                          />
                        </div>
                        <Button onClick={handleCreateOrg} className="w-full">
                          Create Organization
                        </Button>
                      </div>
                    </DialogContent>
                  </Dialog>
                </div>
              </CardHeader>
              <CardContent>
                {organizations.length === 0 ? (
                  <div className="space-y-2">
                    <p className="text-sm text-muted-foreground">No organizations yet.</p>
                    <p className="text-sm text-muted-foreground">Create one to get started!</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {organizations.map((org) => (
                      <Card
                        key={org.org_id}
                        className={`cursor-pointer transition-colors ${
                          selectedOrg?.org_id === org.org_id ? 'border-primary bg-primary/5' : ''
                        }`}
                        onClick={() => setSelectedOrg(org)}
                      >
                        <CardContent className="p-4">
                          <p className="font-medium">{org.name}</p>
                          {org.role && (
                            <Badge variant={getRoleBadgeVariant(org.role)} className="mt-1">
                              {org.role}
                            </Badge>
                          )}
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
          )}

          {/* Members List */}
          <div className={isMemberOfOrg ? 'lg:col-span-1' : 'lg:col-span-2'}>
            {selectedOrg ? (
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle className="flex items-center gap-2">
                        <Users className="h-5 w-5" />
                        Members - {selectedOrg.name}
                      </CardTitle>
                      <CardDescription>
                        {selectedOrg.description || 'No description'}
                        {selectedOrg.default_aws_account_id && (
                          <span className="block mt-1 text-xs">
                            Default AWS Account: {selectedOrg.default_aws_account_id}
                          </span>
                        )}
                      </CardDescription>
                    </div>
                    <div className="flex gap-2">
                      {/* Settings button - show if owner or admin */}
                      {(selectedOrg.role === 'owner' || selectedOrg.role === 'admin') && (
                        <Button
                          variant="outline"
                          onClick={() => navigate(`/organization/${selectedOrg.org_id}/settings`)}
                        >
                          <Settings className="h-4 w-4 mr-2" />
                          Settings
                        </Button>
                      )}
                      {/* Leave Organization button - show if not owner */}
                      {!isOwnerOfSelectedOrg && (
                        <Button
                          variant="destructive"
                          onClick={() => setLeaveDialogOpen(true)}
                        >
                          Leave Organization
                        </Button>
                      )}
                      {(selectedOrg.role === 'owner' || selectedOrg.role === 'admin') && (
                        <Dialog open={inviteDialogOpen} onOpenChange={setInviteDialogOpen}>
                          <DialogTrigger asChild>
                            <Button>
                              <Plus className="h-4 w-4 mr-1" />
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
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {members.map((member) => (
                          <TableRow key={member.user_id}>
                            <TableCell>{member.name || 'N/A'}</TableCell>
                            <TableCell>{member.email}</TableCell>
                            <TableCell>
                              <Badge variant={getRoleBadgeVariant(member.role)}>
                                {member.role}
                              </Badge>
                            </TableCell>
                            <TableCell>
                              {new Date(member.joined_at).toLocaleDateString()}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardContent className="p-8 text-center">
                  <p className="text-muted-foreground">
                    Select an organization to view members, or create a new one to get started.
                  </p>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
        </div>
      </div>

      {/* Pending Invitation Alert Dialog */}
      <AlertDialog open={pendingInviteDialogOpen} onOpenChange={setPendingInviteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Invitation Already Pending</AlertDialogTitle>
            <AlertDialogDescription>
              An invitation has already been sent to <strong>{pendingInviteEmail}</strong> and is still pending.
              Please wait for the user to accept or reject the existing invitation before sending a new one.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogAction onClick={() => setPendingInviteDialogOpen(false)}>
              OK
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Leave Organization Alert Dialog */}
      <AlertDialog open={leaveDialogOpen} onOpenChange={setLeaveDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Leave Organization</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to leave <strong>{selectedOrg?.name}</strong>? You will lose access to all AWS connections and resources associated with this organization.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button variant="outline" onClick={() => setLeaveDialogOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleLeaveOrganization}>
              Leave Organization
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

export default OrganizationManagement;
