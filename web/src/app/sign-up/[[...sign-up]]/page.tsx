import { SignUp } from "@clerk/nextjs";
import AuthFrame from "@/components/AuthFrame";

export default function SignUpPage() {
  return (
    <AuthFrame title="Create your Mindmesh account">
      <SignUp path="/sign-up" routing="path" signInUrl="/sign-in" fallbackRedirectUrl="/claim" />
    </AuthFrame>
  );
}
