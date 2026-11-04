"""Local LN proportion supervision; other technique axes retain chart labels."""
from technique_data import TechniquePatternDataset


class LocalLNTechniqueDataset(TechniquePatternDataset):
    def __getitem__(self, index):
        sample = super().__getitem__(index)
        mask = sample['mask'].astype(bool)
        heads = sum(int(v).bit_count() for v in sample['heads'][mask])
        holds = sum(int(v).bit_count() for v in sample['holds'][mask])
        norm = self.techniques.config['normalization'][str(int(sample['keys']))]
        sample['techniques'] = sample['techniques'].copy()
        sample['techniques'][-1] = (holds / max(1, heads) - norm['mean'][-1]) / norm['std'][-1]
        return sample
