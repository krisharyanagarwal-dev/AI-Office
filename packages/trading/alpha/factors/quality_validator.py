"""
Signal Quality Validator Module
Automated factor validation: IC mean/IR, turnover, crowding, decay curves, sector neutrality
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union, Literal
from dataclasses import dataclass, field
from enum import Enum
import logging
from scipy import stats
from scipy.stats import spearmanr, pearsonr, norm

logger = logging.getLogger(__name__)


class QualityCheck(Enum):
    """Quality check types"""
    IC_MEAN = "ic_mean"
    IC_IR = "ic_ir"
    IC_STABILITY = "ic_stability"
    TURNOVER = "turnover"
    DECAY = "decay"
    SECTOR_NEUTRALITY = "sector_neutrality"
    CROWDING = "crowding"
    DRAWDOWN = "drawdown"
    POSITIVE_IC_RATIO = "positive_ic_ratio"


@dataclass
class QualityThresholds:
    """Thresholds for quality checks"""
    ic_mean_min: float = 0.02          # Minimum IC mean
    ic_ir_min: float = 1.0             # Minimum Information Ratio
    ic_stability_max: float = 0.05     # Maximum IC std
    turnover_max: float = 0.5          # Maximum turnover
    decay_max: float = 0.5             # Maximum decay ratio (horizon_10/horizon_1)
    sector_neutral_ic_min: float = 0.01  # Minimum sector-neutral IC
    crowding_max: float = 100.0        # Maximum crowding score
    drawdown_max: float = 0.10         # Maximum IC drawdown
    positive_ic_ratio_min: float = 0.52  # Minimum positive IC ratio
    min_observations: int = 100        # Minimum observations for statistical significance


@dataclass
class QualityResult:
    """Result of a single quality check"""
    check: QualityCheck
    passed: bool
    value: float
    threshold: float
    message: str
    severity: Literal["info", "warning", "fail"] = "info"


@dataclass
class FactorQualityReport:
    """Complete quality report for a factor"""
    factor_name: str
    overall_pass: bool
    checks: List[QualityResult]
    summary: Dict
    
    def to_dict(self) -> Dict:
        return {
            'factor_name': self.factor_name,
            'overall_pass': self.overall_pass,
            'checks': [
                {
                    'check': c.check.value,
                    'passed': c.passed,
                    'value': c.value,
                    'threshold': c.threshold,
                    'message': c.message,
                    'severity': c.severity,
                }
                for c in self.checks
            ],
            'summary': self.summary,
        }


class SignalQualityValidator:
    """
    Validates factor signal quality across multiple dimensions.
    """
    
    def __init__(
        self,
        thresholds: Optional[QualityThresholds] = None,
        ic_horizons: List[int] = None,
    ):
        self.thresholds = thresholds or QualityThresholds()
        self.ic_horizons = ic_horizons or [1, 5, 10, 20]
    
    def validate_ic_mean(self, ic_mean: float) -> QualityResult:
        """Check if IC mean meets minimum threshold"""
        passed = ic_mean >= self.thresholds.ic_mean_min
        return QualityResult(
            check=QualityCheck.IC_MEAN,
            passed=passed,
            value=ic_mean,
            threshold=self.thresholds.ic_mean_min,
            message=f"IC mean {ic_mean:.4f} {'meets' if passed else 'below'} minimum {self.thresholds.ic_mean_min:.4f}",
            severity="fail" if not passed else "info",
        )
    
    def validate_ic_ir(self, ic_ir: float) -> QualityResult:
        """Check if Information Ratio meets minimum"""
        passed = ic_ir >= self.thresholds.ic_ir_min
        return QualityResult(
            check=QualityCheck.IC_IR,
            passed=passed,
            value=ic_ir,
            threshold=self.thresholds.ic_ir_min,
            message=f"IR {ic_ir:.2f} {'meets' if passed else 'below'} minimum {self.thresholds.ic_ir_min:.2f}",
            severity="fail" if not passed else "info",
        )
    
    def validate_ic_stability(self, ic_std: float, n_obs: int) -> QualityResult:
        """Check IC stability (standard error of IC mean)"""
        # Standard error of IC mean
        se_ic_mean = ic_std / np.sqrt(max(n_obs, 1))
        passed = se_ic_mean <= self.thresholds.ic_stability_max
        return QualityResult(
            check=QualityCheck.IC_STABILITY,
            passed=passed,
            value=se_ic_mean,
            threshold=self.thresholds.ic_stability_max,
            message=f"IC standard error {se_ic_mean:.4f} {'within' if passed else 'exceeds'} limit {self.thresholds.ic_stability_max:.4f}",
            severity="warning" if not passed else "info",
        )
    
    def validate_turnover(self, turnover: float) -> QualityResult:
        """Check factor turnover"""
        passed = turnover <= self.thresholds.turnover_max
        return QualityResult(
            check=QualityCheck.TURNOVER,
            passed=passed,
            value=turnover,
            threshold=self.thresholds.turnover_max,
            message=f"Turnover {turnover:.4f} {'within' if passed else 'exceeds'} limit {self.thresholds.turnover_max:.4f}",
            severity="warning" if not passed else "info",
        )
    
    def validate_decay(self, decay: Dict[int, float]) -> QualityResult:
        """Check IC decay across horizons"""
        if 1 not in decay or 10 not in decay:
            return QualityResult(
                check=QualityCheck.DECAY,
                passed=True,
                value=0.0,
                threshold=self.thresholds.decay_max,
                message="Insufficient decay data (need 1d and 10d horizons)",
                severity="info",
            )
        
        decay_ratio = abs(decay[10]) / abs(decay[1]) if decay[1] != 0 else 0.0
        passed = decay_ratio <= self.thresholds.decay_max
        
        return QualityResult(
            check=QualityCheck.DECAY,
            passed=passed,
            value=decay_ratio,
            threshold=self.thresholds.decay_max,
            message=f"10d/1d decay ratio {decay_ratio:.2f} {'within' if passed else 'exceeds'} limit {self.thresholds.decay_max:.2f}",
            severity="fail" if not passed else "info",
        )
    
    def validate_sector_neutrality(
        self,
        ic_raw: float,
        ic_sector_neutral: float,
    ) -> QualityResult:
        """Check sector-neutral IC"""
        # IC should not drop too much after sector neutralization
        retention = ic_sector_neutral / ic_raw if ic_raw != 0 else 0
        passed = ic_sector_neutral >= self.thresholds.sector_neutral_ic_min and retention > 0.3
        
        return QualityResult(
            check=QualityCheck.SECTOR_NEUTRALITY,
            passed=passed,
            value=ic_sector_neutral,
            threshold=self.thresholds.sector_neutral_ic_min,
            message=f"Sector-neutral IC {ic_sector_neutral:.4f} (retention={retention:.2f}) {'OK' if passed else 'LOW'}",
            severity="warning" if not passed else "info",
        )
    
    def validate_crowding(self, crowding_score: float) -> QualityResult:
        """Check factor crowding"""
        passed = crowding_score <= self.thresholds.crowding_max
        return QualityResult(
            check=QualityCheck.CROWDING,
            passed=passed,
            value=crowding_score,
            threshold=self.thresholds.crowding_max,
            message=f"Crowding score {crowding_score:.1f} {'within' if passed else 'exceeds'} limit {self.thresholds.crowding_max:.1f}",
            severity="info" if passed else "warning",
        )
    
    def validate_drawdown(self, max_drawdown: float) -> QualityResult:
        """Check IC drawdown"""
        passed = abs(max_drawdown) <= self.thresholds.drawdown_max
        return QualityResult(
            check=QualityCheck.DRAWDOWN,
            passed=passed,
            value=abs(max_drawdown),
            threshold=self.thresholds.drawdown_max,
            message=f"Max IC drawdown {abs(max_drawdown):.2%} {'within' if passed else 'exceeds'} limit {self.thresholds.drawdown_max:.2%}",
            severity="warning" if not passed else "info",
        )
    
    def validate_positive_ic_ratio(self, ratio: float) -> QualityResult:
        """Check fraction of periods with positive IC"""
        passed = ratio >= self.thresholds.positive_ic_ratio_min
        return QualityResult(
            check=QualityCheck.POSITIVE_IC_RATIO,
            passed=passed,
            value=ratio,
            threshold=self.thresholds.positive_ic_ratio_min,
            message=f"Positive IC ratio {ratio:.1%} {'meets' if passed else 'below'} minimum {self.thresholds.positive_ic_ratio_min:.1%}",
            severity="fail" if not passed else "info",
        )
    
    def validate_observations(self, n_obs: int) -> QualityResult:
        """Check minimum observations"""
        passed = n_obs >= self.thresholds.min_observations
        return QualityResult(
            check=QualityCheck.IC_STABILITY,  # Reuse stability check
            passed=passed,
            value=n_obs,
            threshold=self.thresholds.min_observations,
            message=f"Observations {n_obs} {'sufficient' if passed else 'insufficient'} (min {self.thresholds.min_observations})",
            severity="fail" if not passed else "info",
        )


class FactorQualityReportGenerator:
    """
    Generates comprehensive quality reports for factors.
    """
    
    def __init__(self, validator: Optional[SignalQualityValidator] = None):
        self.validator = validator or SignalQualityValidator()
    
    def generate_report(
        self,
        factor_name: str,
        ic_result: Dict,  # From ICAnalyzer.analyze_factor
        crowding_score: Optional[float] = None,
    ) -> FactorQualityReport:
        """
        Generate comprehensive quality report from IC analysis results.
        
        Args:
            factor_name: Name of the factor
            ic_result: Dictionary from ICAnalyzer.analyze_factor (or ICResult object)
            crowding_score: Optional crowding score
        
        Returns:
            FactorQualityReport with all checks
        """
        # Extract metrics from IC result
        if hasattr(ic_result, 'ic_mean'):
            # ICResult object
            ic_mean = ic_result.ic_mean
            ic_std = ic_result.ic_std
            ic_ir = ic_result.ic_ir
            ic_t_stat = ic_result.ic_t_stat
            ic_p_value = ic_result.ic_p_value
            positive_ic_ratio = ic_result.positive_ic_ratio
            max_drawdown = ic_result.max_drawdown
            decay = ic_result.decay
            turnover = ic_result.turnover
            n_observations = ic_result.n_observations
            sector_neutral_ic = ic_result.sector_neutral_ic
        else:
            # Dictionary
            ic_mean = ic_result.get('ic_mean', np.nan)
            ic_std = ic_result.get('ic_std', np.nan)
            ic_ir = ic_result.get('ic_ir', np.nan)
            ic_t_stat = ic_result.get('ic_t_stat', np.nan)
            ic_p_value = ic_result.get('ic_p_value', np.nan)
            positive_ic_ratio = ic_result.get('positive_ic_ratio', np.nan)
            max_drawdown = ic_result.get('max_drawdown', np.nan)
            decay = ic_result.get('decay', {})
            turnover = ic_result.get('turnover', np.nan)
            n_observations = ic_result.get('n_observations', 0)
            sector_neutral_ic = ic_result.get('sector_neutral_ic', np.nan)
        
        checks = []
        
        # Run all checks
        checks.append(self.validator.validate_ic_mean(ic_mean))
        checks.append(self.validator.validate_ic_ir(ic_ir))
        checks.append(self.validator.validate_ic_stability(ic_std, n_observations))
        checks.append(self.validator.validate_turnover(turnover))
        checks.append(self.validator.validate_decay(decay))
        checks.append(self.validator.validate_drawdown(max_drawdown))
        checks.append(self.validator.validate_positive_ic_ratio(positive_ic_ratio))
        checks.append(self.validator.validate_observations(n_observations))
        
        if sector_neutral_ic is not None and not np.isnan(sector_neutral_ic):
            checks.append(self.validator.validate_sector_neutrality(ic_mean, sector_neutral_ic))
        
        if crowding_score is not None:
            checks.append(self.validator.validate_crowding(crowding_score))
        
        # Overall pass: all "fail" severity checks must pass
        overall_pass = all(c.passed or c.severity != "fail" for c in checks)
        
        # Summary
        summary = {
            'total_checks': len(checks),
            'passed': sum(1 for c in checks if c.passed),
            'failed': sum(1 for c in checks if not c.passed),
            'warnings': sum(1 for c in checks if not c.passed and c.severity == "warning"),
            'critical_failures': sum(1 for c in checks if not c.passed and c.severity == "fail"),
        }
        
        return FactorQualityReport(
            factor_name=factor_name,
            overall_pass=overall_pass,
            checks=checks,
            summary=summary,
        )
    
    def batch_validate(
        self,
        factor_results: Dict[str, Dict],  # factor_name -> ic_result
        crowding_scores: Optional[Dict[str, float]] = None,
    ) -> Dict[str, FactorQualityReport]:
        """Validate multiple factors"""
        reports = {}
        for name, result in factor_results.items():
            crowding = crowding_scores.get(name) if crowding_scores else None
            reports[name] = self.generate_report(name, result, crowding)
        return reports


class FactorScreeningPipeline:
    """
    Pipeline for screening factors through quality gates.
    """
    
    def __init__(
        self,
        validator: Optional[SignalQualityValidator] = None,
        min_pass_rate: float = 0.8,
    ):
        self.validator = validator or SignalQualityValidator()
        self.report_generator = FactorQualityReportGenerator(self.validator)
        self.min_pass_rate = min_pass_rate
    
    def screen_factors(
        self,
        factor_results: Dict[str, Dict],
        crowding_scores: Optional[Dict[str, float]] = None,
    ) -> Tuple[List[str], List[str], Dict[str, FactorQualityReport]]:
        """
        Screen factors through quality gates.
        
        Returns:
            passed_factors, failed_factors, all_reports
        """
        reports = self.report_generator.batch_validate(factor_results, crowding_scores)
        
        passed = []
        failed = []
        
        for name, report in reports.items():
            if report.overall_pass:
                passed.append(name)
            else:
                failed.append(name)
        
        # Check overall pass rate
        pass_rate = len(passed) / len(reports) if reports else 0
        if pass_rate < self.min_pass_rate:
            logger.warning(f"Low pass rate: {pass_rate:.1%} (min {self.min_pass_rate:.1%})")
        
        return passed, failed, reports
    
    def get_factor_ranking(
        self,
        factor_results: Dict[str, Dict],
        crowding_scores: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        """
        Rank factors by quality score.
        """
        reports = self.report_generator.batch_validate(factor_results, crowding_scores)
        
        rows = []
        for name, report in reports.items():
            checks_dict = {c.check.value: c for c in report.checks}
            
            rows.append({
                'factor': name,
                'overall_pass': report.overall_pass,
                'quality_score': report.summary['passed'] / max(report.summary['total_checks'], 1),
                'ic_mean': checks_dict.get('ic_mean', QualityResult(QualityCheck.IC_MEAN, False, 0, 0, "")).value,
                'ic_ir': checks_dict.get('ic_ir', QualityResult(QualityCheck.IC_IR, False, 0, 0, "")).value,
                'turnover': checks_dict.get('turnover', QualityResult(QualityCheck.TURNOVER, False, 0, 0, "")).value,
                'decay_ratio': checks_dict.get('decay', QualityResult(QualityCheck.DECAY, False, 0, 0, "")).value,
                'positive_ic_ratio': checks_dict.get('positive_ic_ratio', QualityResult(QualityCheck.POSITIVE_IC_RATIO, False, 0, 0, "")).value,
                'max_drawdown': checks_dict.get('drawdown', QualityResult(QualityCheck.DRAWDOWN, False, 0, 0, "")).value,
            })
        
        df = pd.DataFrame(rows)
        df = df.sort_values('quality_score', ascending=False).reset_index(drop=True)
        return df


def validate_factor_quality(
    factor_name: str,
    ic_result: Dict,
    crowding_score: Optional[float] = None,
    thresholds: Optional[QualityThresholds] = None,
) -> FactorQualityReport:
    """Convenience function for single factor validation"""
    validator = SignalQualityValidator(thresholds)
    generator = FactorQualityReportGenerator(validator)
    return generator.generate_report(factor_name, ic_result, crowding_score)


def screen_factors(
    factor_results: Dict[str, Dict],
    crowding_scores: Optional[Dict[str, float]] = None,
    thresholds: Optional[QualityThresholds] = None,
    min_pass_rate: float = 0.8,
) -> Tuple[List[str], List[str], Dict[str, FactorQualityReport]]:
    """Convenience function for batch factor screening"""
    validator = SignalQualityValidator(thresholds)
    pipeline = FactorScreeningPipeline(validator, min_pass_rate)
    return pipeline.screen_factors(factor_results, crowding_scores)


if __name__ == "__main__":
    # Quick test
    from alpha.factors.ic_analysis import ICAnalyzer, ICResult
    
    np.random.seed(42)
    n = 300
    dates = pd.date_range('2020-01-01', periods=n, freq='D')
    
    # Good factor
    factor_good = pd.Series(np.random.normal(0, 1, n), index=dates)
    returns = pd.DataFrame({
        1: factor_good * 0.3 + np.random.normal(0, 0.5, n),
        5: (factor_good * 0.2).rolling(5).sum() + np.random.normal(0, 1, n),
        10: (factor_good * 0.1).rolling(10).sum() + np.random.normal(0, 1.5, n),
    }, index=dates)
    
    analyzer = ICAnalyzer()
    result = analyzer.analyze_factor('good_factor', factor_good, returns)
    
    # Validate
    report = validate_factor_quality('good_factor', result)
    print(f"Factor: {report.factor_name}")
    print(f"Overall Pass: {report.overall_pass}")
    print(f"Summary: {report.summary}")
    for check in report.checks:
        print(f"  {check.check.value}: {'PASS' if check.passed else 'FAIL'} - {check.message}")