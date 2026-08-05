import { ReportViewerClient } from "@/components/reports/report-viewer-client";

export default async function ReportViewerPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ReportViewerClient reportId={id} />;
}
