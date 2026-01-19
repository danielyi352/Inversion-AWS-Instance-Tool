import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Building2, Cloud, ArrowRight } from 'lucide-react';
import { getCurrentUser } from '@/lib/api';
import { AppHeader } from '@/components/AppHeader';

const MainDashboard = () => {
  const navigate = useNavigate();

  useEffect(() => {
    // Check if user is authenticated
    const userSessionId = localStorage.getItem('user_session_id');
    
    if (!userSessionId) {
      navigate('/login');
      return;
    }

    // Verify session is still valid
    getCurrentUser()
      .then(() => {
        // Session is valid, stay on page
      })
      .catch(() => {
        localStorage.removeItem('user_session_id');
        navigate('/login');
      });
  }, [navigate]);

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <div className="p-8">
      <div className="max-w-6xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Welcome to Inversion Deployer</h1>
          <p className="text-muted-foreground">Manage your organizations and AWS deployments</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Organization Card */}
          <Card 
            className="cursor-pointer hover:shadow-lg transition-shadow"
            onClick={() => navigate('/organization')}
          >
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="p-3 bg-primary/10 rounded-lg">
                  <Building2 className="h-8 w-8 text-primary" />
                </div>
                <div className="flex-1">
                  <CardTitle className="text-2xl">Organization</CardTitle>
                  <CardDescription>Manage your team and invite members</CardDescription>
                </div>
                <ArrowRight className="h-5 w-5 text-muted-foreground" />
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Create organizations, invite team members, and manage AWS account connections.
              </p>
            </CardContent>
          </Card>

          {/* AWS Card */}
          <Card 
            className="cursor-pointer hover:shadow-lg transition-shadow"
            onClick={() => navigate('/aws')}
          >
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="p-3 bg-primary/10 rounded-lg">
                  <Cloud className="h-8 w-8 text-primary" />
                </div>
                <div className="flex-1">
                  <CardTitle className="text-2xl">AWS</CardTitle>
                  <CardDescription>Deploy and manage EC2 instances</CardDescription>
                </div>
                <ArrowRight className="h-5 w-5 text-muted-foreground" />
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Connect AWS accounts, deploy Docker containers, and manage your infrastructure.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
      </div>
    </div>
  );
};

export default MainDashboard;
