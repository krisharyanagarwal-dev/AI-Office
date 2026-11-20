"""
Tests for Signal Quality Validator Module
"""
import numpy as np
import pandas as pd
import pytest
from alpha.factors.quality_validator import (
    QualityCheck,
    QualityThresholds,
    QualityResult,
    FactorQualityReport,
    SignalQualityValidator,
    FactorQualityReportGenerator,
    FactorScreeningPipeline,
    validate_factor_quality,
    screen_factors,
)


class TestQualityThresholds:
    def test_default_thresholds(self):
        t = QualityThresholds()
        assert t.ic_mean_min == 0.02
        assert t.ic_ir_min == 1.0
        assert t.turnover_max == 0.5
        assert t.decay_max == 0.5
        assert t.positive_ic_ratio_min == 0.52
    
    def test_custom_thresholds(self):
        t = QualityThresholds(ic_mean_min=0.05, ic_ir_min=2.0)
        assert t.ic_mean_min == 0.05
        assert t.ic_ir_min == 2.0


class TestQualityResult:
    def test_creation(self):
        result = QualityResult(
            check=QualityCheck.IC_MEAN,
            passed=True,
            value=0.05,
            threshold=0.02,
            message="Test message",
            severity="info",
        )
        assert result.check == QualityCheck.IC_MEAN
        assert result.passed is True
        assert result.value == 0.05


class TestSignalQualityValidator:
    def test_validate_ic_mean_pass(self):
        t = QualityThresholds(ic_mean_min=0.02)
        v = SignalQualityValidator(t)
        result = v.validate_ic_mean(0.05)
        assert result.passed is True
        assert result.check == QualityCheck.IC_MEAN
    
    def test_validate_ic_mean_fail(self):
        t = QualityThresholds(ic_mean_min=0.02)
        v = SignalQualityValidator(t)
        result = v.validate_ic_mean(0.01)
        assert result.passed is False
        assert result.severity == "fail"
    
    def test_validate_ic_ir_pass(self):
        t = QualityThresholds(ic_ir_min=1.0)
        v = SignalQualityValidator(t)
        result = v.validate_ic_ir(2.5)
        assert result.passed is True
    
    def test_validate_ic_ir_fail(self):
        t = QualityThresholds(ic_ir_min=1.0)
        v = SignalQualityValidator(t)
        result = v.validate_ic_ir(0.5)
        assert result.passed is False
        assert result.severity == "fail"
    
    def test_validate_turnover_pass(self):
        t = QualityThresholds(turnover_max=0.5)
        v = SignalQualityValidator(t)
        result = v.validate_turnover(0.3)
        assert result.passed is True
    
    def test_validate_turnover_fail(self):
        t = QualityThresholds(turnover_max=0.5)
        v = SignalQualityValidator(t)
        result = v.validate_turnover(0.8)
        assert result.passed is False
        assert result.severity == "warning"
    
    def test_validate_decay_pass(self):
        t = QualityThresholds(decay_max=0.5)
        v = SignalQualityValidator(t)
        result = v.validate_decay({1: 0.05, 5: 0.04, 10: 0.02})
        assert result.passed is True
    
    def test_validate_decay_fail(self):
        t = QualityThresholds(decay_max=0.5)
        v = SignalQualityValidator(t)
        result = v.validate_decay({1: 0.05, 10: 0.04})  # 80% retention
        assert result.passed is False
        assert result.severity == "fail"
    
    def test_validate_decay_insufficient_data(self):
        v = SignalQualityValidator()
        result = v.validate_decay({1: 0.05})  # Missing 10d
        assert result.passed is True  # Should pass with warning
        assert "Insufficient" in result.message
    
    def test_validate_sector_neutrality_pass(self):
        v = SignalQualityValidator()
        result = v.validate_sector_neutrality(0.05, 0.04)
        assert result.passed is True
    
    def test_validate_sector_neutrality_fail(self):
        v = SignalQualityValidator()
        result = v.validate_sector_neutrality(0.05, 0.005)  # 10% retention
        assert result.passed is False
        assert result.severity == "warning"
    
    def test_validate_drawdown_pass(self):
        v = SignalQualityValidator()
        result = v.validate_drawdown(-0.05)
        assert result.passed is True
    
    def test_validate_drawdown_fail(self):
        v = SignalQualityValidator()
        result = v.validate_drawdown(-0.15)
        assert result.passed is False
        assert result.severity == "warning"
    
    def test_validate_positive_ic_ratio_pass(self):
        v = SignalQualityValidator()
        result = v.validate_positive_ic_ratio(0.6)
        assert result.passed is True
    
    def test_validate_positive_ic_ratio_fail(self):
        v = SignalQualityValidator()
        result = v.validate_positive_ic_ratio(0.45)
        assert result.passed is False
        assert result.severity == "fail"
    
    def test_validate_observations_pass(self):
        v = SignalQualityValidator()
        result = v.validate_observations(200)
        assert result.passed is True
    
    def test_validate_observations_fail(self):
        v = SignalQualityValidator()
        result = v.validate_observations(50)
        assert result.passed is False
        assert result.severity == "fail"


class TestFactorQualityReportGenerator:
    def test_generate_report_good_factor(self):
        from alpha.factors.ic_analysis import ICResult
        
        ic_result = ICResult(
            factor_name='test',
            ic_mean=0.05,
            ic_std=0.02,
            ic_ir=2.5,
            ic_t_stat=10.0,
            ic_p_value=0.001,
            positive_ic_ratio=0.6,
            max_drawdown=-0.03,
            decay={1: 0.05, 5: 0.04, 10: 0.02},
            turnover=0.2,
            sector_neutral_ic=0.04,
            n_observations=200,
        )
        
        generator = FactorQualityReportGenerator()
        report = generator.generate_report('test_factor', ic_result)
        
        assert report.factor_name == 'test_factor'
        assert report.overall_pass is True
        assert len(report.checks) > 0
        assert report.summary['passed'] > 0
    
    def test_generate_report_bad_factor(self):
        from alpha.factors.ic_analysis import ICResult
        
        ic_result = ICResult(
            factor_name='bad',
            ic_mean=0.005,  # Below threshold
            ic_std=0.05,
            ic_ir=0.1,  # Below threshold
            ic_t_stat=0.5,
            ic_p_value=0.5,
            positive_ic_ratio=0.45,  # Below threshold
            max_drawdown=-0.15,  # Exceeds threshold
            decay={1: 0.05, 10: 0.04},  # High decay
            turnover=0.8,  # Exceeds threshold
            sector_neutral_ic=0.005,
            n_observations=50,  # Below threshold
        )
        
        generator = FactorQualityReportGenerator()
        report = generator.generate_report('bad_factor', ic_result)
        
        assert report.overall_pass is False
        assert report.summary['critical_failures'] > 0
    
    def test_generate_report_from_dict(self):
        ic_result = {
            'ic_mean': 0.05,
            'ic_std': 0.02,
            'ic_ir': 2.5,
            'ic_t_stat': 10.0,
            'ic_p_value': 0.001,
            'positive_ic_ratio': 0.6,
            'max_drawdown': -0.03,
            'decay': {1: 0.05, 5: 0.04, 10: 0.02},
            'turnover': 0.2,
            'sector_neutral_ic': 0.04,
            'n_observations': 200,
        }
        
        generator = FactorQualityReportGenerator()
        report = generator.generate_report('dict_factor', ic_result)
        
        assert report.factor_name == 'dict_factor'
        assert report.overall_pass is True
    
    def test_batch_validate(self):
        from alpha.factors.ic_analysis import ICResult
        
        factor_results = {
            'good': ICResult(
                factor_name='good', ic_mean=0.05, ic_std=0.02, ic_ir=2.5,
                ic_t_stat=10, ic_p_value=0.001, positive_ic_ratio=0.6,
                max_drawdown=-0.03, decay={1: 0.05, 10: 0.02}, turnover=0.2,
                sector_neutral_ic=0.04, n_observations=200
            ),
            'bad': ICResult(
                factor_name='bad', ic_mean=0.005, ic_std=0.05, ic_ir=0.1,
                ic_t_stat=0.5, ic_p_value=0.5, positive_ic_ratio=0.45,
                max_drawdown=-0.15, decay={1: 0.05, 10: 0.04}, turnover=0.8,
                sector_neutral_ic=0.005, n_observations=50
            ),
        }
        
        generator = FactorQualityReportGenerator()
        reports = generator.batch_validate(factor_results)
        
        assert len(reports) == 2
        assert reports['good'].overall_pass is True
        assert reports['bad'].overall_pass is False


class TestFactorScreeningPipeline:
    def test_screen_factors(self):
        from alpha.factors.ic_analysis import ICResult
        
        factor_results = {
            'good': ICResult(
                factor_name='good', ic_mean=0.05, ic_std=0.02, ic_ir=2.5,
                ic_t_stat=10, ic_p_value=0.001, positive_ic_ratio=0.6,
                max_drawdown=-0.03, decay={1: 0.05, 10: 0.02}, turnover=0.2,
                sector_neutral_ic=0.04, n_observations=200
            ),
            'bad': ICResult(
                factor_name='bad', ic_mean=0.005, ic_std=0.05, ic_ir=0.1,
                ic_t_stat=0.5, ic_p_value=0.5, positive_ic_ratio=0.45,
                max_drawdown=-0.15, decay={1: 0.05, 10: 0.04}, turnover=0.8,
                sector_neutral_ic=0.005, n_observations=50
            ),
            'ok': ICResult(
                factor_name='ok', ic_mean=0.03, ic_std=0.02, ic_ir=1.5,
                ic_t_stat=5, ic_p_value=0.01, positive_ic_ratio=0.55,
                max_drawdown=-0.05, decay={1: 0.04, 10: 0.015}, turnover=0.4,
                sector_neutral_ic=0.025, n_observations=150
            ),
        }
        
        pipeline = FactorScreeningPipeline()
        passed, failed, reports = pipeline.screen_factors(factor_results)
        
        assert 'good' in passed
        assert 'ok' in passed
        assert 'bad' in failed
        assert len(passed) == 2
        assert len(failed) == 1
    
    def test_get_factor_ranking(self):
        from alpha.factors.ic_analysis import ICResult
        
        factor_results = {
            'good': ICResult(
                factor_name='good', ic_mean=0.05, ic_std=0.02, ic_ir=2.5,
                ic_t_stat=10, ic_p_value=0.001, positive_ic_ratio=0.6,
                max_drawdown=-0.03, decay={1: 0.05, 10: 0.02}, turnover=0.2,
                sector_neutral_ic=0.04, n_observations=200
            ),
            'bad': ICResult(
                factor_name='bad', ic_mean=0.005, ic_std=0.05, ic_ir=0.1,
                ic_t_stat=0.5, ic_p_value=0.5, positive_ic_ratio=0.45,
                max_drawdown=-0.15, decay={1: 0.05, 10: 0.04}, turnover=0.8,
                sector_neutral_ic=0.005, n_observations=50
            ),
        }
        
        pipeline = FactorScreeningPipeline()
        ranking = pipeline.get_factor_ranking(factor_results)
        
        assert len(ranking) == 2
        assert ranking.iloc[0]['factor'] == 'good'
        assert ranking.iloc[1]['factor'] == 'bad'
        assert ranking.iloc[0]['quality_score'] > ranking.iloc[1]['quality_score']


class TestConvenienceFunctions:
    def test_validate_factor_quality(self):
        from alpha.factors.ic_analysis import ICResult
        
        ic_result = ICResult(
            factor_name='test', ic_mean=0.05, ic_std=0.02, ic_ir=2.5,
            ic_t_stat=10, ic_p_value=0.001, positive_ic_ratio=0.6,
            max_drawdown=-0.03, decay={1: 0.05, 10: 0.02}, turnover=0.2,
            sector_neutral_ic=0.04, n_observations=200
        )
        
        report = validate_factor_quality('test', ic_result)
        assert report.overall_pass is True
    
    def test_screen_factors_function(self):
        from alpha.factors.ic_analysis import ICResult
        
        factor_results = {
            'good': ICResult(
                factor_name='good', ic_mean=0.05, ic_std=0.02, ic_ir=2.5,
                ic_t_stat=10, ic_p_value=0.001, positive_ic_ratio=0.6,
                max_drawdown=-0.03, decay={1: 0.05, 10: 0.02}, turnover=0.2,
                sector_neutral_ic=0.04, n_observations=200
            ),
            'bad': ICResult(
                factor_name='bad', ic_mean=0.005, ic_std=0.05, ic_ir=0.1,
                ic_t_stat=0.5, ic_p_value=0.5, positive_ic_ratio=0.45,
                max_drawdown=-0.15, decay={1: 0.05, 10: 0.04}, turnover=0.8,
                sector_neutral_ic=0.005, n_observations=50
            ),
        }
        
        passed, failed, reports = screen_factors(factor_results)
        
        assert 'good' in passed
        assert 'bad' in failed


class TestQualityThresholdsCustomization:
    def test_custom_thresholds_strict(self):
        thresholds = QualityThresholds(
            ic_mean_min=0.05,
            ic_ir_min=2.0,
            turnover_max=0.3,
            decay_max=0.3,
            positive_ic_ratio_min=0.55,
        )
        
        v = SignalQualityValidator(thresholds)
        
        # These would pass default but fail strict
        assert v.validate_ic_mean(0.03).passed is False
        assert v.validate_ic_ir(1.5).passed is False
        assert v.validate_turnover(0.4).passed is False
        assert v.validate_positive_ic_ratio(0.53).passed is False
    
    def test_custom_thresholds_lenient(self):
        thresholds = QualityThresholds(
            ic_mean_min=0.005,
            ic_ir_min=0.5,
            turnover_max=1.0,
            decay_max=0.8,
            positive_ic_ratio_min=0.45,
        )
        
        v = SignalQualityValidator(thresholds)
        
        assert v.validate_ic_mean(0.01).passed is True
        assert v.validate_ic_ir(0.6).passed is True
        assert v.validate_turnover(0.8).passed is True
        assert v.validate_positive_ic_ratio(0.48).passed is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])