import ProtectedLayout from "../lib/protected";
import BusinessGate from "./BusinessGate";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedLayout>
      <BusinessGate>{children}</BusinessGate>
    </ProtectedLayout>
  );
}
