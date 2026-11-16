# Cloud Cost Optimization Analysis
## AWS Startup - $K/Month Spend

**Prepared by:** Cloud Security Architect
**Date:** 2026-11-05
**Task ID:** 37bc0825
**Priority:** Normal

---

## Executive Summary

This analysis provides targeted cost optimization strategies for a startup running on AWS with approximately $K/month spend. The recommendations are organized by service category (compute, storage, data transfer) with specific, actionable items ranked by impact vs. effort.

**Estimated Total Savings Potential:** 25-40% ($2.5K-$4K/month) with full implementation

---

## Current State Assumptions

| Parameter | Assumption |
|-----------|------------|
| Monthly Spend | ~$10K/month |
| Primary Workloads | Web applications, APIs, databases, background workers |
| Environment | Single AWS account, us-east-1 primary |
| Team Size | 5-15 engineers |
| Growth Trajectory | 2-3x year-over-year |

---

## 1. COMPUTE OPTIMIZATION (Highest Impact: 30-50% of compute spend)

### 1.1 Right-Sizing EC2 Instances
**Savings Potential:** 20-35% of EC2 spend
**Effort:** Medium | **Risk:** Low

| Current Instance | Recommended | Monthly Savings (est.) |
|------------------|-------------|------------------------|
| t3.xlarge (4 vCPU, 16 GB) | t3.large (2 vCPU, 8 GB) | $180/instance |
| m5.2xlarge (8 vCPU, 32 GB) | m5.xlarge (4 vCPU, 16 GB) | $320/instance |
| c5.4xlarge (16 vCPU, 32 GB) | c5.2xlarge (8 vCPU, 16 GB) | $450/instance |

**Action Items:**
- [ ] Enable **Compute Optimizer** (free) → Get ML-based recommendations
- [ ] Run `aws ec2 describe-instances` + CloudWatch metrics (CPUUtilization, MemoryUtilization) for 14-day window
- [ ] Target: CPU < 40% avg, Memory < 60% avg → downsize
- [ ] Test in staging before production changes

### 1.2 Savings Plans / Reserved Instances
**Savings Potential:** 30-65% vs On-Demand
**Effort:** Low | **Risk:** Low (with proper planning)

| Commitment Type | Discount | Best For |
|-----------------|----------|----------|
| **Compute Savings Plan** (1yr, No Upfront) | ~27% | Flexible instance family/size/region |
| **EC2 Instance Savings Plan** (1yr, No Upfront) | ~35% | Specific instance family |
| **Standard RI** (1yr, Partial Upfront) | ~40% | Stable, predictable workloads |
| **Convertible RI** (1yr, Partial Upfront) | ~31% | Need flexibility to change instance family |

**Recommendation:** Start with **Compute Savings Plan (1yr, No Upfront)** for 70% of baseline compute. Covers EC2, Fargate, Lambda.

### 1.3 Spot Instances for Fault-Tolerant Workloads
**Savings Potential:** 60-90% vs On-Demand
**Effort:** Medium | **Risk:** Medium

**Ideal Candidates:**
- Batch processing / ETL jobs
- CI/CD build runners
- Development/staging environments
- Containerized stateless workers (ECS Fargate Spot, EKS managed node groups with Spot)

**Implementation:**
```yaml
# ECS Service with capacity provider strategy
capacityProviderStrategy:
  - capacityProvider: FARGATE_SPOT
    weight: 4
    base: 1
  - capacityProvider: FARGATE
    weight: 1
```

### 1.4 Graviton Migration (ARM-based)
**Savings Potential:** 20-40% better price/performance
**Effort:** Medium-High | **Risk:** Medium (arch compatibility)

**Target Workloads:**
- Containerized apps (Docker multi-arch builds)
- Node.js, Python, Go, Java 11+ applications
- Databases: Aurora PostgreSQL/MySQL on Graviton, ElastiCache Graviton

**Migration Path:**
1. Build multi-arch images: `docker buildx build --platform linux/amd64,linux/arm64`
2. Test in staging with Graviton instances
3. Deploy via blue/green to production

### 1.5 Lambda Optimization
**Savings Potential:** 15-30% of Lambda spend
**Effort:** Low | **Risk:** Low

| Optimization | Impact |
|--------------|--------|
| Right-size memory (test 128MB → 10GB) | 20-50% cost reduction per invocation |
| Use **Lambda Power Tuning** (open source) | Automated optimization |
| Enable **Provisioned Concurrency** only where needed | Avoid cold starts without over-provisioning |
| Migrate to **Lambda ARM (Graviton2)** | 34% better price/performance |

---

## 2. STORAGE OPTIMIZATION (15-25% of storage spend)

### 2.1 S3 Lifecycle Policies
**Savings Potential:** 40-80% on aging data
**Effort:** Low | **Risk:** None

```json
{
  "Rules": [
    {
      "ID": "MoveToIAAfter30Days",
      "Status": "Enabled",
      "Filter": {"Prefix": "logs/"},
      "Transitions": [
        {"Days": 30, "StorageClass": "STANDARD_IA"},
        {"Days": 90, "StorageClass": "GLACIER_IR"},
        {"Days": 365, "StorageClass": "GLACIER"},
        {"Days": 2555, "StorageClass": "DEEP_ARCHIVE"}
      ]
    },
    {
      "ID": "DeleteIncompleteMPU",
      "Status": "Enabled",
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
    }
  ]
}
```

**Storage Class Comparison (us-east-1, per GB/month):**
| Class | Cost | Min Duration | Retrieval |
|-------|------|--------------|-----------|
| Standard | $0.023 | - | Instant |
| Standard-IA | $0.0125 | 30 days | Instant (per GB fee) |
| Glacier IR | $0.004 | 90 days | Hours |
| Glacier | $0.0036 | 90 days | Hours |
| Deep Archive | $0.00099 | 180 days | 12-48 hours |

### 2.2 S3 Intelligent-Tiering
**Savings Potential:** 20-50% for unpredictable access patterns
**Effort:** Low | **Risk:** None

- Enable on buckets with unknown/variable access patterns
- Automatic tiering between Frequent, Infrequent, Archive, Deep Archive
- $0.0025/month per 1K objects monitoring fee (worth it for >100K objects)

### 2.3 EBS Volume Optimization
**Savings Potential:** 20-40% of EBS spend
**Effort:** Low | **Risk:** Low

| Action | Savings |
|--------|---------|
| Delete unattached volumes (run weekly) | 5-15% |
| Convert gp2 → gp3 (20% cheaper, better baseline IOPS) | 20% |
| Right-size provisioned IOPS (io1/io2 Block Express) | 30-50% |
| Enable **EBS Snapshots Archive** for snapshots > 90 days | 75% on archive storage |

**gp2 → gp3 Migration:**
```bash
aws ec2 modify-volume --volume-id vol-xxx --volume-type gp3 --iops 3000 --throughput 125
```
*No downtime required for most volume types.*

### 2.4 RDS Storage Optimization
**Savings Potential:** 15-30% of RDS storage spend
**Effort:** Low | **Risk:** Low

- Enable **Storage Autoscaling** (max threshold) instead of over-provisioning
- Use **GP3 for RDS** (available for MySQL, PostgreSQL, MariaDB)
- Delete automated snapshots beyond retention policy
- Consider **Aurora Serverless v2** for variable workloads (scales to 0)

### 2.5 EFS Optimization
**Savings Potential:** 30-50% of EFS spend
**Effort:** Low | **Risk:** Low

- Enable **EFS Lifecycle Management** → Move to IA after 7/14/30 days
- Use **EFS One Zone** for dev/staging (47% cheaper, single AZ)
- Monitor `StorageBytes` vs `MeteredIOBytes` ratio

---

## 3. DATA TRANSFER OPTIMIZATION (10-20% of network spend)

### 3.1 CloudFront + S3 Origin
**Savings Potential:** 50-90% on data transfer out to internet
**Effort:** Low | **Risk:** Low

| Path | Cost/GB (us-east-1) |
|------|---------------------|
| EC2/ALB → Internet | $0.09 |
| S3 → Internet | $0.09 |
| **CloudFront → Internet** | **$0.085** (first 10TB) → **$0.06** (10-50TB) |
| **CloudFront + S3 (Origin Shield)** | **$0.02** (origin fetches) |

**Implementation:**
- Move static assets to S3 + CloudFront
- Enable **Origin Shield** (reduces origin requests by 60-80%)
- Configure **Cache-Control** headers properly (max-age, stale-while-revalidate)

### 3.2 VPC Endpoints (Gateway/Interface)
**Savings Potential:** $0.01/GB on S3/DynamoDB + eliminate NAT Gateway costs
**Effort:** Low | **Risk:** None

| Service | Endpoint Type | Savings |
|---------|---------------|---------|
| S3 | Gateway (free) | Eliminates NAT GW data processing ($0.045/GB) |
| DynamoDB | Gateway (free) | Same |
| SQS, SNS, Kinesis, Secrets Manager, etc. | Interface ($0.01/hr/AZ + $0.01/GB) | Avoids NAT GW |

**NAT Gateway Cost Breakdown:**
- Hourly: $0.045/hr/AZ = ~$33/month/AZ
- Data Processing: $0.045/GB
- **Typical NAT GW cost: $100-500/month per AZ**

### 3.3 Regional Architecture
**Savings Potential:** Eliminate cross-AZ / cross-region transfer
**Effort:** Medium | **Risk:** Low

- Keep communicating services in **same AZ** where possible
- Use **AZ IDs** (not names) for consistent mapping across accounts
- For multi-AZ HA: prefer **same-region replication** over cross-region
- Cross-region replication: $0.02/GB (vs $0.09 internet egress)

### 3.4 Data Transfer Cost Monitoring
**Effort:** Low | **Ongoing**

```sql
-- Athena query on CUR (Cost and Usage Report)
SELECT 
  line_item_usage_type,
  SUM(line_item_usage_amount) AS gb_transferred,
  SUM(line_item_unblended_cost) AS cost
FROM cur_table
WHERE line_item_usage_type LIKE '%DataTransfer%'
  AND line_item_usage_start_date >= DATE_TRUNC('month', CURRENT_DATE)
GROUP BY 1
ORDER BY 3 DESC;
```

---

## 4. QUICK WINS (Implement This Week)

| # | Action | Est. Monthly Savings | Effort |
|---|--------|---------------------|--------|
| 1 | Delete unattached EBS volumes | $200-500 | 30 min |
| 2 | Enable S3 Lifecycle on log buckets | $300-800 | 1 hour |
| 3 | Convert gp2 → gp3 volumes | $200-600 | 2 hours |
| 4 | Enable S3 Gateway Endpoint | $50-200 | 15 min |
| 5 | Enable Compute Savings Plan (70% baseline) | $1,500-3,000 | 30 min |
| 6 | Delete old snapshots (>90 days) | $100-400 | 1 hour |
| 7 | Right-size 5 largest EC2 instances | $500-1,500 | 4 hours |
| 8 | Enable CloudFront for static assets | $300-1,000 | 2 hours |

**Total Quick Wins: ~$3,150-8,000/month**

---

## 5. MEDIUM-TERM INITIATIVES (1-3 Months)

| Initiative | Est. Savings | Timeline |
|------------|-------------|----------|
| Graviton migration (container workloads) | 20-40% compute | 4-8 weeks |
| Spot fleet for batch/CI workloads | 60-80% those workloads | 2-4 weeks |
| Aurora Serverless v2 for variable DBs | 30-60% DB compute | 2-4 weeks |
| ECS/EKS Fargate Spot + Savings Plans | 40-60% container compute | 3-6 weeks |
| Implement FinOps dashboard (QuickSight/Grafana) | Visibility → better decisions | 2-3 weeks |

---

## 6. GOVERNANCE & ONGOING OPTIMIZATION

### 6.1 FinOps Practices
- **Weekly:** Review Cost Explorer anomalies, unattached resources
- **Monthly:** Right-sizing review, RI/SP utilization check
- **Quarterly:** Architecture review for cost efficiency
- **Annually:** Savings Plan renewal optimization

### 6.2 Tagging Strategy (Mandatory)
```
Environment: production | staging | development
Team: platform | backend | frontend | data
Project: user-api | payment-service | analytics
Owner: slack-handle or email
CostCenter: eng | product | infra
```
**Enforce via:** AWS Config Rules + Service Control Policies

### 6.3 Budget Alerts
```bash
# Monthly budget at 80% forecast
aws budgets create-budget --account-id $ACCOUNT_ID --budget '{
  "BudgetName": "Monthly-Overall",
  "BudgetLimit": {"Amount": "10000", "Unit": "USD"},
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}' --notifications-with-subscribers '[{
  "Notification": {
    "NotificationType": "FORECASTED",
    "ComparisonOperator": "GREATER_THAN",
    "Threshold": 80,
    "ThresholdType": "PERCENTAGE"
  },
  "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "finops@company.com"}]
}]'
```

### 6.4 Automated Cleanup (Lambda + EventBridge)
- Daily: Delete unattached EBS volumes > 7 days old
- Weekly: Delete EBS snapshots > retention policy
- Monthly: Report on idle Load Balancers, unused EIPs, old AMIs

---

## 7. COST ALLOCATION & CHARGEBACK

### 7.1 Enable Cost Allocation Tags
Activate in Billing Console → Cost Allocation Tags:
- User-defined tags (Environment, Team, Project, Owner)
- AWS-generated tags (aws:createdBy, aws:cloudformation:stack-name)

### 7.2 Team-Level Cost Visibility
- Create **Cost Categories** in Billing Console
- Build **QuickSight dashboard** per team
- Monthly "cost review" in sprint retro

---

## 8. SECURITY CONSIDERATIONS (Zero-Trust Alignment)

| Optimization | Security Implication | Mitigation |
|--------------|---------------------|------------|
| Spot Instances | Instance termination (2-min notice) | Graceful shutdown handlers, checkpointing |
| Savings Plans | Vendor lock-in (1yr) | Compute SP = flexible; monitor utilization |
| Graviton | ARM compatibility | Multi-arch CI/CD, staged rollout |
| S3 Intelligent-Tiering | Data access patterns visible | Encryption at rest (SSE-S3/KMS) always on |
| VPC Endpoints | Traffic stays in AWS backbone | No public internet exposure |

---

## 9. IMPLEMENTATION ROADMAP

### Week 1-2: Quick Wins
- [ ] Delete unattached resources (EBS, EIP, snapshots, LBs)
- [ ] Enable S3 Lifecycle + Intelligent-Tiering
- [ ] gp2 → gp3 migration
- [ ] S3/DynamoDB Gateway Endpoints
- [ ] Purchase Compute Savings Plan (70% baseline)

### Week 3-4: Right-Sizing & Visibility
- [ ] Compute Optimizer recommendations → apply to staging
- [ ] Enable Cost Allocation Tags + Cost Categories
- [ ] Build FinOps dashboard (QuickSight)
- [ ] Set up Budget Alerts (80% forecast, 100% actual)

### Month 2: Architecture Optimization
- [ ] CloudFront + Origin Shield for static assets
- [ ] VPC Interface Endpoints for high-volume services
- [ ] Lambda memory right-sizing + Graviton migration
- [ ] Spot Fleet for CI/CD and batch workloads

### Month 3: Advanced Optimization
- [ ] Graviton migration for container workloads
- [ ] Aurora Serverless v2 evaluation
- [ ] Cross-region replication cost review
- [ ] Reserved Instance / Savings Plan true-up

---

## 10. MEASUREMENT & SUCCESS METRICS

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Total Monthly Spend** | ↓ 30% ($7K from $10K) | CUR + Cost Explorer |
| **Compute Unit Cost** | ↓ 35% ($/vCPU-hour) | Compute Optimizer + CUR |
| **Storage Unit Cost** | ↓ 40% ($/GB-month) | S3 Storage Lens + CUR |
| **Data Transfer Cost** | ↓ 50% ($/GB) | CUR (DataTransfer line items) |
| **Savings Plan Utilization** | > 85% | Savings Plans Console |
| **RI/SP Coverage** | > 70% of baseline | Cost Explorer → RI/SP |
| **Unattached Resources** | 0 | Weekly automated audit |
| **Tag Coverage** | 100% on billable resources | AWS Config Rule |

---

## Appendix A: Useful AWS CLI Commands

```bash
# Find unattached EBS volumes
aws ec2 describe-volumes --filters Name=status,Values=available --query 'Volumes[*].[VolumeId,Size,AvailabilityZone,CreateTime]' --output table

# Find old snapshots (>90 days)
aws ec2 describe-snapshots --owner-ids self --query 'Snapshots[?StartTime<=`2026-08-07`].[SnapshotId,VolumeId,StartTime,VolumeSize]' --output table

# Find idle Load Balancers (no requests in 7 days)
aws cloudwatch get-metric-statistics --namespace AWS/ApplicationELB --metric-name RequestCount --dimensions Name=LoadBalancer,Value=app/xxx --start-time 2026-10-29T00:00:00Z --end-time 2026-11-05T00:00:00Z --period 86400 --statistics Sum

# Find unused Elastic IPs
aws ec2 describe-addresses --query 'Addresses[?AssociationId==null].[PublicIp,AllocationId]' --output table

# Get Compute Optimizer recommendations
aws compute-optimizer get-ec2-instance-recommendations --filters Name=Finding,Values=Underprovisioned,Overprovisioned
```

---

## Appendix B: Recommended Tools

| Category | Tool | Purpose |
|----------|------|---------|
| **Native** | AWS Compute Optimizer | ML-based right-sizing |
| **Native** | AWS Cost Explorer | Visualization, forecasting |
| **Native** | S3 Storage Lens | Storage analytics |
| **Native** | Trusted Advisor (Business+) | Best practice checks |
| **Open Source** | Cloud Custodian | Policy-as-code cleanup |
| **Open Source** | Lambda Power Tuning | Lambda memory optimization |
| **Open Source** | kube-cost (Kubecost) | Kubernetes cost allocation |
| **Commercial** | Vantage / Cloudability / CloudHealth | Advanced FinOps |

---

## Next Steps

1. **Immediate (Today):** Run the quick-win CLI commands above to identify unattached resources
2. **This Week:** Purchase Compute Savings Plan, enable S3 Lifecycle, gp2→gp3
3. **This Month:** Implement CloudFront, VPC Endpoints, FinOps dashboard
4. **Ongoing:** Monthly cost review, quarterly architecture optimization

---

*Document Version: 1.0*
*Classification: Internal - Engineering*
*Next Review: 2026-12-05*