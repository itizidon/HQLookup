import type { Metadata } from 'next';
import AcceptInviteForm from './AcceptInviteForm';

export const metadata: Metadata = {
  title: 'Accept invitation | HQLookup',
};

export default function AcceptInvitePage() {
  return <AcceptInviteForm />;
}
