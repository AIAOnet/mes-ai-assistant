CREATE OR ALTER TRIGGER dbo.TR_Alarms_AuditStatusChange
ON dbo.Alarms
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT dbo.AlarmAudit (AlarmId, PreviousStatus, NewStatus)
    SELECT inserted.AlarmId, deleted.Status, inserted.Status
    FROM inserted
    INNER JOIN deleted ON deleted.AlarmId = inserted.AlarmId
    WHERE inserted.Status <> deleted.Status;
END;
GO

