import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SwiftShaderDescriptorTraceTests(unittest.TestCase):
    def test_sampling_trace_uses_allocation_generation_and_draw_identity(self):
        patch = (ROOT / 'experiments/m1e/patches/'
                 'swiftshader_coherent_diagnostic.patch').read_text()
        self.assertIn('AaasDiagnosticObjectCreate(descriptorSet)', patch)
        self.assertIn('AAAS_DESCRIPTOR_SET_CREATE', patch)
        self.assertIn('AAAS_DESCRIPTOR_SET_RETIRE', patch)
        self.assertIn('AAAS_DESCRIPTOR_USE submit_id=%llu draw_id=%llu', patch)
        self.assertIn('AaasDiagnosticSetDrawContext(diagnosticSubmissionId', patch)

    def test_sampling_trace_is_emitted_at_prepare_for_sampling(self):
        patch = (ROOT / 'experiments/m1e/patches/'
                 'swiftshader_coherent_diagnostic.patch').read_text()
        self.assertIn('notificationType == PREPARE_FOR_SAMPLING', patch)
        self.assertIn('memory->getOffsetPointer(0)', patch)
        self.assertIn('AaasDiagnosticObjectId(memoryOwner)', patch)
        self.assertIn('AaasDiagnosticObjectId(image)', patch)
        self.assertIn('AaasDiagnosticObjectId(memory)', patch)


if __name__ == '__main__':
    unittest.main()
