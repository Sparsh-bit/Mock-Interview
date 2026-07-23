import type { Metadata, Viewport } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import { Providers } from '@/components/providers';
import { Toaster } from 'sonner';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: {
    default: 'InterviewOS — AI-Powered Mock Interviews',
    template: '%s | InterviewOS',
  },
  description:
    'Practice technical interviews with AI. Adaptive questions, real-time evaluation, and expert feedback for Cognizant, TCS, Infosys, and Wipro.',
  keywords: [
    'mock interview',
    'technical interview',
    'Cognizant Digital Nurture',
    'Java interview practice',
    'AI interview simulator',
    'coding interview prep',
  ],
  authors: [{ name: 'InterviewOS' }],
  creator: 'InterviewOS',
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL || 'https://interviewos.dev'),
  openGraph: {
    type: 'website',
    locale: 'en_US',
    url: 'https://interviewos.dev',
    title: 'InterviewOS — AI-Powered Mock Interviews',
    description:
      'The interview simulator built for real offers. Adaptive AI questioning, resume personalization, and detailed performance reports.',
    siteName: 'InterviewOS',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'InterviewOS — AI-Powered Mock Interviews',
    description: 'Practice technical interviews with AI and land your dream offer.',
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: '#0a0d14',
  colorScheme: 'dark',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable} dark`}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-background font-sans antialiased">
        <Providers>
          {children}
          <Toaster
            theme="dark"
            position="bottom-right"
            toastOptions={{
              style: {
                background: 'hsl(222 14% 8%)',
                border: '1px solid hsl(217 19% 17%)',
                color: 'hsl(210 40% 96%)',
              },
            }}
          />
        </Providers>
      </body>
    </html>
  );
}
