import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { googleLogin, getCurrentUser } from '@/lib/api';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";

const Login = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scriptLoaded, setScriptLoaded] = useState(false);

  // Check if user is already logged in
  useEffect(() => {
    const userSessionId = localStorage.getItem('user_session_id');
    if (userSessionId) {
      // Verify session is still valid
      getCurrentUser()
        .then(() => {
          navigate('/dashboard');
        })
        .catch(() => {
          localStorage.removeItem('user_session_id');
        });
    }
  }, [navigate]);

  const handleGoogleCallback = async (response: any) => {
    setLoading(true);
    setError(null);

    try {
      const data = await googleLogin(response.credential);
      
      // Store user session ID
      localStorage.setItem('user_session_id', data.session_id);
      
      toast.success('Successfully logged in!');
      
      // Redirect to dashboard
      navigate('/dashboard');
    } catch (err: any) {
      setError(err.message || 'Login failed');
      setLoading(false);
    }
  };

  // Load Google Identity Services script
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || scriptLoaded) return;

    const loadGoogleScript = async () => {
      try {
        // Check if script already exists
        if (window.google?.accounts) {
          setScriptLoaded(true);
          return;
        }

        await new Promise<void>((resolve, reject) => {
          const script = document.createElement('script');
          script.src = 'https://accounts.google.com/gsi/client';
          script.async = true;
          script.defer = true;
          script.onload = () => resolve();
          script.onerror = () => reject(new Error('Failed to load Google Identity Services'));
          
          // Check if script already exists
          const existingScript = document.querySelector('script[src="https://accounts.google.com/gsi/client"]');
          if (existingScript) {
            resolve();
            return;
          }
          
          document.head.appendChild(script);
        });

        setScriptLoaded(true);
      } catch (err) {
        console.error('Failed to load Google Sign-In:', err);
        setError('Failed to load Google Sign-In. Please refresh the page.');
      }
    };

    loadGoogleScript();
  }, [GOOGLE_CLIENT_ID, scriptLoaded]);

  // Initialize and render Google Sign-In button
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || !scriptLoaded || loading) return;

    try {
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleGoogleCallback,
      });

      // Render the button
      const buttonContainer = document.getElementById('google-signin-button');
      if (buttonContainer) {
        window.google.accounts.id.renderButton(buttonContainer, {
          theme: 'outline',
          size: 'large',
          width: 300,
          text: 'signin_with',
        });
      }
    } catch (err) {
      console.error('Failed to initialize Google Sign-In:', err);
      setError('Failed to initialize Google Sign-In.');
    }
  }, [GOOGLE_CLIENT_ID, scriptLoaded, loading]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <div className="flex items-center justify-center mb-4">
            <svg className="h-12 w-12" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2L2 7L12 12L22 7L12 2Z" className="fill-foreground" />
              <path d="M2 17L12 22L22 17" className="stroke-foreground" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M2 12L12 17L22 12" className="stroke-foreground" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <CardTitle className="text-2xl text-center">Inversion Deployer</CardTitle>
          <CardDescription className="text-center">
            Sign in to manage your AWS deployments
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="flex flex-col items-center space-y-4">
            <div id="google-signin-button" className="w-full flex justify-center" />
            
            {!GOOGLE_CLIENT_ID && (
              <Alert>
                <AlertDescription>
                  Google OAuth is not configured. Please set VITE_GOOGLE_CLIENT_ID environment variable.
                </AlertDescription>
              </Alert>
            )}

            {loading && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Signing in...</span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

// Extend Window interface for Google types
declare global {
  interface Window {
    google: any;
  }
}

export default Login;
