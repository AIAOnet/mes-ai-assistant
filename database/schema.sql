IF OBJECT_ID(N'dbo.Machines', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Machines (
        MachineId nvarchar(50) NOT NULL CONSTRAINT PK_Machines PRIMARY KEY,
        DisplayName nvarchar(100) NOT NULL,
        CreatedTime datetimeoffset(3) NOT NULL CONSTRAINT DF_Machines_Created DEFAULT SYSDATETIMEOFFSET()
    );
END;
GO

IF OBJECT_ID(N'dbo.MachineReadings', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.MachineReadings (
        ReadingId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_MachineReadings PRIMARY KEY,
        MachineId nvarchar(50) NOT NULL,
        TagName nvarchar(100) NOT NULL,
        NumericValue float NULL,
        TextValue nvarchar(200) NULL,
        RecordedTime datetimeoffset(3) NOT NULL CONSTRAINT DF_Readings_Time DEFAULT SYSDATETIMEOFFSET(),
        CONSTRAINT FK_Readings_Machine FOREIGN KEY (MachineId) REFERENCES dbo.Machines(MachineId)
    );
    CREATE INDEX IX_Readings_Machine_Time ON dbo.MachineReadings(MachineId, RecordedTime DESC);
END;
GO

IF OBJECT_ID(N'dbo.[Events]', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.[Events] (
        EventId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_Events PRIMARY KEY,
        MachineId nvarchar(50) NOT NULL,
        EventType nvarchar(50) NOT NULL,
        ConditionName nvarchar(100) NOT NULL,
        NumericValue float NOT NULL,
        OccurredTime datetimeoffset(3) NOT NULL,
        CONSTRAINT FK_Events_Machine FOREIGN KEY (MachineId) REFERENCES dbo.Machines(MachineId)
    );
    CREATE INDEX IX_Events_Machine_Time ON dbo.[Events](MachineId, OccurredTime DESC);
END;
GO

IF OBJECT_ID(N'dbo.Alarms', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Alarms (
        AlarmId nvarchar(30) NOT NULL CONSTRAINT PK_Alarms PRIMARY KEY,
        MachineId nvarchar(50) NOT NULL,
        AlarmType nvarchar(100) NOT NULL,
        Severity nvarchar(20) NOT NULL,
        Message nvarchar(500) NOT NULL,
        TriggeredValue float NOT NULL,
        TriggeredTime datetimeoffset(3) NOT NULL,
        Status nvarchar(20) NOT NULL,
        Acknowledged bit NOT NULL CONSTRAINT DF_Alarms_Acknowledged DEFAULT 0,
        AcknowledgedBy nvarchar(100) NULL,
        AcknowledgedTime datetimeoffset(3) NULL,
        ResolvedTime datetimeoffset(3) NULL,
        CONSTRAINT FK_Alarms_Machine FOREIGN KEY (MachineId) REFERENCES dbo.Machines(MachineId),
        CONSTRAINT CK_Alarms_Status CHECK (Status IN ('ACTIVE', 'RESOLVED'))
    );
    CREATE INDEX IX_Alarms_Machine_Status ON dbo.Alarms(MachineId, Status, TriggeredTime DESC);
END;
GO

IF OBJECT_ID(N'dbo.MaintenanceTasks', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.MaintenanceTasks (
        TaskId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_MaintenanceTasks PRIMARY KEY,
        MachineId nvarchar(50) NOT NULL,
        RelatedAlarmId nvarchar(30) NULL,
        Description nvarchar(500) NOT NULL,
        Priority nvarchar(20) NOT NULL,
        Status nvarchar(20) NOT NULL,
        CreatedTime datetimeoffset(3) NOT NULL CONSTRAINT DF_Tasks_Created DEFAULT SYSDATETIMEOFFSET(),
        CompletedTime datetimeoffset(3) NULL,
        CONSTRAINT FK_Tasks_Machine FOREIGN KEY (MachineId) REFERENCES dbo.Machines(MachineId),
        CONSTRAINT FK_Tasks_Alarm FOREIGN KEY (RelatedAlarmId) REFERENCES dbo.Alarms(AlarmId),
        CONSTRAINT CK_Tasks_Status CHECK (Status IN ('OPEN', 'IN_PROGRESS', 'COMPLETED'))
    );
    CREATE INDEX IX_Tasks_Machine_Status ON dbo.MaintenanceTasks(MachineId, Status);
END;
GO

IF OBJECT_ID(N'dbo.ProductionOrders', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.ProductionOrders (
        ProductionOrderId nvarchar(50) NOT NULL CONSTRAINT PK_ProductionOrders PRIMARY KEY,
        MachineId nvarchar(50) NOT NULL,
        ProductName nvarchar(100) NOT NULL,
        TargetQuantity int NOT NULL,
        Status nvarchar(20) NOT NULL,
        StartedTime datetimeoffset(3) NULL,
        CompletedTime datetimeoffset(3) NULL,
        CONSTRAINT FK_Orders_Machine FOREIGN KEY (MachineId) REFERENCES dbo.Machines(MachineId),
        CONSTRAINT CK_Orders_Target CHECK (TargetQuantity > 0)
    );
END;
GO

IF COL_LENGTH('dbo.ProductionOrders', 'ProductName') IS NULL
BEGIN
    ALTER TABLE dbo.ProductionOrders ADD ProductName nvarchar(100) NOT NULL
        CONSTRAINT DF_ProductionOrders_ProductName DEFAULT N'Unspecified';
END;
GO

IF OBJECT_ID(N'dbo.ProductionRecords', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.ProductionRecords (
        ProductionRecordId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_ProductionRecords PRIMARY KEY,
        ProductionOrderId nvarchar(50) NOT NULL,
        TotalQuantity int NOT NULL,
        GoodQuantity int NOT NULL,
        RejectedQuantity int NOT NULL,
        RecordedTime datetimeoffset(3) NOT NULL CONSTRAINT DF_ProductionRecords_Time DEFAULT SYSDATETIMEOFFSET(),
        CONSTRAINT FK_Records_Order FOREIGN KEY (ProductionOrderId) REFERENCES dbo.ProductionOrders(ProductionOrderId),
        CONSTRAINT CK_Records_Quantities CHECK (
            TotalQuantity >= 0 AND GoodQuantity >= 0 AND RejectedQuantity >= 0
            AND TotalQuantity = GoodQuantity + RejectedQuantity
        )
    );
    CREATE INDEX IX_ProductionRecords_Order_Time ON dbo.ProductionRecords(ProductionOrderId, RecordedTime DESC);
END;
GO

IF OBJECT_ID(N'dbo.AlarmAudit', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.AlarmAudit (
        AuditId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_AlarmAudit PRIMARY KEY,
        AlarmId nvarchar(30) NOT NULL,
        PreviousStatus nvarchar(20) NOT NULL,
        NewStatus nvarchar(20) NOT NULL,
        ChangedTime datetimeoffset(3) NOT NULL CONSTRAINT DF_AlarmAudit_Time DEFAULT SYSDATETIMEOFFSET(),
        CONSTRAINT FK_AlarmAudit_Alarm FOREIGN KEY (AlarmId) REFERENCES dbo.Alarms(AlarmId)
    );
END;
GO

IF OBJECT_ID(N'dbo.OperatorActionAudit', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.OperatorActionAudit (
        ActionAuditId bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_OperatorActionAudit PRIMARY KEY,
        Username nvarchar(100) NOT NULL,
        UserRole nvarchar(20) NOT NULL,
        HttpMethod nvarchar(10) NOT NULL,
        ActionPath nvarchar(300) NOT NULL,
        ResultStatus int NOT NULL,
        ClientAddress nvarchar(100) NULL,
        OccurredTime datetimeoffset(3) NOT NULL CONSTRAINT DF_OperatorActionAudit_Time DEFAULT SYSDATETIMEOFFSET()
    );
    CREATE INDEX IX_OperatorActionAudit_Time ON dbo.OperatorActionAudit(OccurredTime DESC);
END;
GO

MERGE dbo.Machines AS target
USING (SELECT N'MACHINE-01' AS MachineId, N'Machine 01' AS DisplayName) AS source
ON target.MachineId = source.MachineId
WHEN NOT MATCHED THEN
    INSERT (MachineId, DisplayName) VALUES (source.MachineId, source.DisplayName);
GO
