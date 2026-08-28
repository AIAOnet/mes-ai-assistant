CREATE OR ALTER PROCEDURE dbo.GetMachineAlarmHistory
    @MachineId nvarchar(50)
AS
BEGIN
    SET NOCOUNT ON;

    SELECT
        AlarmId,
        MachineId,
        AlarmType,
        Severity,
        Message,
        TriggeredValue,
        TriggeredTime,
        Status,
        Acknowledged,
        AcknowledgedBy,
        AcknowledgedTime,
        ResolvedTime
    FROM dbo.Alarms
    WHERE MachineId = @MachineId
    ORDER BY TriggeredTime DESC;
END;
GO

