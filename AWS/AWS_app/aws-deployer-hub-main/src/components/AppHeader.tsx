import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { LogOut } from 'lucide-react';
import { LogoutDialog } from '@/components/deployer/LogoutDialog';
import { logout } from '@/lib/api';
import { toast } from 'sonner';

export function AppHeader() {
  const navigate = useNavigate();
  const [logoutDialogOpen, setLogoutDialogOpen] = useState(false);

  const handleLogout = async () => {
    try {
      await logout();
      localStorage.removeItem('user_session_id');
      localStorage.removeItem('aws_session_id');
      toast.success('Logged out successfully');
      navigate('/login');
    } catch (error: any) {
      toast.error(`Logout failed: ${error.message}`);
    }
  };

  return (
    <>
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

      <LogoutDialog
        open={logoutDialogOpen}
        onOpenChange={setLogoutDialogOpen}
        onConfirm={handleLogout}
      />
    </>
  );
}
